"""
自动化整理方案解析与审查纠偏仲裁器 (Automation Plan Resolver)

恪守五大基本原则与面向对象核心：
1. 主路由表为主、元数据为辅：
   - 首要命中 TopologyRoutingTable 主路由表；
   - 冲突时以 PE/发行商等强元数据为准 (MasterConflictResolver 仲裁)；
   - 无元数据资产 (相册照片、视频、散装文档) 委托 AI 深度理解。
2. 绝对纠偏绝不降级：
   - 识别中转目录污染 (如 Downloads/共用文件/临时下载)，强力剥离中转容器名；
   - 生成 AuditCorrectionRecord 伴生诊断，赋予 [AI已纠偏] 明确标签。
3. 分析完成即写入主路由表：
   - 在候选方案提炼与分组完成后，立即自沉淀写入 TopologyRoutingTable，绝不在归档后重复用工。
4. 用户手动修改绝对覆盖法则：
   - P1 (USER_CONFIRMED) > P2 (AI_LEARNED) > P3 (SYSTEM_BUILTIN)，用户配置绝对神圣。
5. 人为可操控的 AI 审查机制与全域生态联动：
   - 严格绑定 AIAuditPolicyConfig 阈值；
   - 遇低置信度 (< threshold) 或高风险时，自动拦截无人值守物理平移，转为候选提议待人工审核。
"""

import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.core.domain_models import (
    TopologyRoutingTable,
    MasterConflictResolver,
    AuditCorrectionRecord,
    AIAuditPolicyConfig,
    KnowledgeProvenance
)
from app.automation.models import WatchRule, ProposedPlan
from app.utils.logger import app_logger


class AutomationPlanResolver:
    """
    自动化整理方案解析器 (Automation Plan Resolver)
    """

    @classmethod
    def resolve_plan(
        cls,
        rule: WatchRule,
        settled_files: List[Dict[str, Any]],
        now: float
    ) -> Tuple[ProposedPlan, bool]:
        """
        全量解析已沉淀文件集，生成携带 AI 纠偏诊断的 ProposedPlan，
        并返回是否因安全审查机制强制转为仅提议 (enforce_propose_only)。

        Returns:
            Tuple[ProposedPlan, bool]: (候选方案对象, 是否触发安全拦截转为提议)
        """
        target_root = rule.target_dir or "D:/归档备份"
        mode_val = rule.organize_mode or "comprehensive"
        try:
            mode_enum = OrganizeMode(mode_val)
        except Exception:
            mode_enum = OrganizeMode.COMPREHENSIVE

        options = OrganizeOptions(mode=mode_enum)

        # 1. 基础拓扑分组
        groups = AppDetector.group_files_by_parent_or_tool(settled_files, target_root, options)

        # 2. 结合主路由表、元数据仲裁与 AI 审查策略执行全量审查与纠偏
        audit_policy = AIAuditPolicyConfig.get_instance()
        routing_table = TopologyRoutingTable.instance()

        correction_records: List[AuditCorrectionRecord] = []
        is_plan_corrected = False
        enforce_propose_only = False
        downgrade_reasons: List[str] = []

        for group in groups:
            pe_meta = group.get("high_value_metadata") or group.get("metadata") or {}
            group["high_value_metadata"] = pe_meta
            group_name = group.get("name") or group.get("app_name") or ""
            candidate_name = pe_meta.get("software_name") or group_name
            orig_root = group.get("original_root") or rule.watch_path
            is_dir = bool(group.get("is_directory_group", False))

            # 2.1 主冲突仲裁器判定 (原则一：主路由表为主 + 元数据仲裁)
            status, matched_rule, correction = MasterConflictResolver.resolve_candidate(
                candidate_name=candidate_name,
                original_root=orig_root,
                pe_metadata=pe_meta,
                is_directory_group=is_dir,
                audit_policy=audit_policy
            )

            # 若顶层组名未命中，进一步探测子项文件是否命中主路由规则
            if not matched_rule and group.get("sub_items"):
                for sub in group["sub_items"]:
                    sub_name = sub.get("name", "")
                    sub_match = routing_table.match_master_rule(sub_name)
                    if sub_match:
                        matched_rule = sub_match
                        if sub_match.provenance == KnowledgeProvenance.USER_CONFIRMED:
                            break

            # 2.2 绝对纠偏 (原则二：纠偏绝不降级)
            if correction:
                correction_records.append(correction)
                is_plan_corrected = True
                # 标记该组为 AI 审查/纠偏源，赋予沉淀凭证
                group["source"] = "AI (主动纠偏)"
                # 若为剥离中转名或元数据纠偏，更新组内推荐路径与分类
                if correction.correction_type == "STRIP_STAGING":
                    # 强力剥离中转名
                    old_sub = group.get("recommended_subpath") or group.get("target_subpath") or ""
                    cleaned_sub = routing_table.should_strip_from_target(old_sub)
                    if cleaned_sub:
                        group["recommended_subpath"] = cleaned_sub
                        group["target_subpath"] = cleaned_sub
                    group["effective_category"] = "软件安装与程序 (Apps & Installers)"
                    group["suggested_category"] = "软件安装与程序 (Apps & Installers)"
                elif correction.correction_type == "METADATA_MISMATCH":
                    group["app_name"] = correction.corrected_target
                    group["effective_category"] = correction.corrected_target

            # 2.3 检查是否命中用户确认的规则 (原则四：用户修改绝对覆盖)
            if matched_rule:
                if matched_rule.provenance == KnowledgeProvenance.USER_CONFIRMED or not group.get("effective_category"):
                    group["effective_category"] = matched_rule.target_category
                    group["suggested_category"] = matched_rule.target_category
                    if matched_rule.target_subpath_template:
                        group["recommended_subpath"] = matched_rule.target_subpath_template
                        group["target_subpath"] = matched_rule.target_subpath_template

            # 2.4 人为可操控的 AI 审查安全门禁 (原则五)
            confidence = float(group.get("confidence", 1.0))
            if confidence < audit_policy.confidence_threshold:
                enforce_propose_only = True
                downgrade_reasons.append(
                    f"资产 [{app_name}] AI置信度 ({confidence:.2f}) 低于安全阈值 ({audit_policy.confidence_threshold:.2f})"
                )
            if group.get("risk_level") == "高风险":
                enforce_propose_only = True
                downgrade_reasons.append(f"资产 [{app_name}] 判定为高风险资产，严禁自动静默移动")

        # 3. 分析完成即刻沉淀自学习写入主路由表 (原则三)
        precipitated_count = routing_table.precipitate_ai_decisions(
            groups,
            min_confidence=audit_policy.confidence_threshold
        )
        if precipitated_count > 0:
            app_logger.info("自动化中心: 分析完成即刻自沉淀 %d 条新规则至全局主路由表", precipitated_count)

        total_bytes = sum(f.get("size", 0) for f in settled_files)

        notes = f"监控规则 [{rule.name}] 捕获到 {len(settled_files)} 个稳定文件，已生成整理候选计划"
        if is_plan_corrected:
            notes += f" (已由 AI 实施主动纠偏: 共 {len(correction_records)} 项)"
        if enforce_propose_only and not rule.propose_only:
            notes += " [🛡️ 触发 AI 审查安全门禁: 转为人工审核提案]"

        plan = ProposedPlan(
            source_type="rule_monitor",
            source_name=rule.name,
            source_path=rule.watch_path,
            target_root=target_root,
            created_at=now,
            file_count=len(settled_files),
            total_bytes=total_bytes,
            proposed_groups=groups,
            status="pending",
            notes=notes,
            is_corrected=is_plan_corrected,
            correction_records=[c.to_dict() for c in correction_records]
        )

        return plan, enforce_propose_only
