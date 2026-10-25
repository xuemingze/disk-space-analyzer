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

from app.config import app_config
from app.core.ai_service import AIService
from app.core.app_detector import AppDetector
from app.core.organize_models import OrganizeOptions, OrganizeMode
from app.core.domain_models import (
    TopologyRoutingTable,
    MasterConflictResolver,
    AuditCorrectionRecord,
    AIAuditPolicyConfig,
    KnowledgeProvenance,
    ArchiveDestinationPath
)
from app.automation.models import WatchRule, ScheduledTask, ProposedPlan
from app.utils.logger import app_logger


class AutomationPlanResolver:
    """
    自动化整理方案解析器 (Automation Plan Resolver)
    统一承载「规则监控」、「计划任务」、「快速整理」三大自动化场景的：
    1. 主路由表秒级命中与 PE 元数据三阶冲突仲裁；
    2. 在线 AI 核心编排器接入 (AIService.classify_files_with_ai)；
    3. 中转容器污染主动纠偏 (AuditCorrectionRecord)；
    4. 分析完成即刻沉淀入全局拓扑主路由表；
    5. 人为可操控的 AI 审查置信度与风险安全门禁。
    """

    @classmethod
    def resolve_assets_plan(
        cls,
        source_type: str,
        source_name: str,
        source_path: str,
        target_root: str,
        organize_mode: str,
        propose_only: bool,
        settled_files: List[Dict[str, Any]],
        now: float
    ) -> Tuple[ProposedPlan, bool]:
        """
        统一多态资产方案解析与 AI 编排审查核心方法
        Returns:
            Tuple[ProposedPlan, bool]: (候选方案对象, 是否触发安全拦截强制转为提议)
        """
        dest_root = target_root or "D:/归档备份"
        mode_val = organize_mode or "comprehensive"
        try:
            mode_enum = OrganizeMode(mode_val)
        except Exception:
            mode_enum = OrganizeMode.COMPREHENSIVE

        audit_policy = AIAuditPolicyConfig.get_instance()
        options = OrganizeOptions(
            mode=mode_enum,
            min_confidence=audit_policy.confidence_threshold if audit_policy.enabled else 0.75,
            custom_instructions=audit_policy.custom_instruction_prompt or ""
        )

        # 1. 优先调用在线 AI 核心编排器，无模型或异常时安全平滑降级至本地拓扑引擎
        llm_cfg = app_config.get("llm", default={})
        api_key = str(llm_cfg.get("api_key", "")).strip()
        base_url = str(llm_cfg.get("base_url", "")).strip()
        model = str(llm_cfg.get("model", "")).strip()

        groups = None
        is_ai_powered = False

        if api_key and base_url and model and settled_files:
            try:
                app_logger.info(
                    "自动化中心 [%s-%s]: 启动在线 AI 核心编排器为 %d 个资产制定归档方案...",
                    source_type, source_name, len(settled_files)
                )
                groups = AIService.classify_files_with_ai(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    file_items=settled_files,
                    destination_root=dest_root,
                    options=options
                )
                if groups:
                    is_ai_powered = True
                    app_logger.info(
                        "自动化中心 [%s-%s]: AI 核心编排成功完成，提炼出 %d 个聚合单元",
                        source_type, source_name, len(groups)
                    )
            except Exception as e:
                app_logger.warning("自动化中心在线 AI 分类异常，平滑降级至离线拓扑引擎: %s", e)

        if not groups:
            groups = AppDetector.group_files_by_parent_or_tool(settled_files, dest_root, options)

        # 2. 结合主路由表、元数据仲裁与 AI 审查策略执行全量审查与纠偏
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
            orig_root = group.get("original_root") or source_path
            is_dir = bool(group.get("is_directory_group", False))

            # 2.1 主冲突仲裁器判定 (原则一：主路由表为主 + 元数据仲裁)
            status, matched_rule, correction = MasterConflictResolver.resolve_candidate(
                candidate_name=candidate_name,
                original_root=orig_root,
                pe_metadata=pe_meta,
                is_directory_group=is_dir,
                audit_policy=audit_policy
            )

            # 探测子项文件是否有更高优先级的规则 (特别是 USER_CONFIRMED 绝对覆盖)
            if group.get("sub_items"):
                for sub in group["sub_items"]:
                    sub_name = sub.get("name", "")
                    sub_match = routing_table.match_master_rule(sub_name)
                    if sub_match:
                        if sub_match.provenance == KnowledgeProvenance.USER_CONFIRMED:
                            matched_rule = sub_match
                            break
                        elif not matched_rule:
                            matched_rule = sub_match

            # 2.2 绝对纠偏 (原则二：纠偏绝不降级)
            if correction:
                correction_records.append(correction)
                is_plan_corrected = True
                group["source"] = "AI (主动纠偏)"
                group["action"] = "已纠偏"
                group["correction_record"] = correction.to_dict()
                if correction.correction_type == "STRIP_STAGING":
                    old_sub = str(group.get("recommended_subpath") or group.get("target_subpath") or "")
                    parts = [p for p in old_sub.replace("\\", "/").split("/") if p and not routing_table.should_strip_from_target(p)]
                    cleaned_sub = "/".join(parts)
                    if not cleaned_sub:
                        cleaned_sub = f"软件安装与程序/{candidate_name}"
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
                    if matched_rule.provenance == KnowledgeProvenance.USER_CONFIRMED:
                        group["confidence"] = 1.0
                        group["risk_level"] = "低风险"
                        group["require_confirmation"] = False
                        group["rationale"] = f"命中用户锁定主路由规则 (P1): {matched_rule.pattern}"

            # 同步重算标准化归档目标路径 target_root
            eff_cat = group.get("effective_category") or group.get("suggested_category") or ""
            eff_sub = group.get("recommended_subpath") or group.get("target_subpath") or ""
            if eff_cat:
                dest_obj = ArchiveDestinationPath.build(
                    dest_root=dest_root,
                    category=eff_cat,
                    subpath=eff_sub,
                    entity_name=Path(orig_root).name if orig_root else candidate_name,
                    is_dir=is_dir
                )
                group["target_root"] = str(dest_obj.path)

            # 2.4 人为可操控的 AI 审查安全门禁 (原则五)
            if audit_policy.enabled:
                confidence = float(group.get("confidence", 1.0))
                risk = group.get("risk_level", "低风险")
                if confidence < audit_policy.confidence_threshold:
                    enforce_propose_only = True
                    downgrade_reasons.append(
                        f"资产 [{candidate_name}] 置信度 ({confidence:.2f}) 低于安全阈值 ({audit_policy.confidence_threshold:.2f})"
                    )
                elif risk in ["高风险", "需人工确认"]:
                    enforce_propose_only = True
                    downgrade_reasons.append(f"资产 [{candidate_name}] 判定为高风险资产，严禁自动静默移动")

        # 3. 分析完成即刻沉淀自学习写入主路由表 (原则三)
        precipitated_count = routing_table.precipitate_ai_decisions(
            groups,
            min_confidence=audit_policy.confidence_threshold
        )
        if precipitated_count > 0:
            app_logger.info("自动化中心 [%s-%s]: 分析完成即刻自沉淀 %d 条新规则至全局主路由表", source_type, source_name, precipitated_count)

        total_bytes = sum(f.get("size", 0) for f in settled_files)
        plan_origin = "AI 核心编排" if is_ai_powered else "规则引擎"
        scene_label = {
            "rule_monitor": f"监控规则 [{source_name}]",
            "scheduled_task": f"计划任务 [{source_name}]",
            "quick_organize": f"快速整理 [{source_name}]"
        }.get(source_type, f"[{source_name}]")

        notes = f"{scene_label} 捕获到 {len(settled_files)} 个资产文件，已由 {plan_origin} 生成整理候选计划"
        if is_plan_corrected:
            notes += f" (已由 AI 实施主动纠偏: 共 {len(correction_records)} 项)"
        if enforce_propose_only and not propose_only:
            notes += " [🛡️ 触发 AI 审查安全门禁: 转为人工审核提案]"

        plan = ProposedPlan(
            source_type=source_type,
            source_name=source_name,
            source_path=source_path,
            target_root=dest_root,
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

    @classmethod
    def resolve_plan(
        cls,
        rule: WatchRule,
        settled_files: List[Dict[str, Any]],
        now: float
    ) -> Tuple[ProposedPlan, bool]:
        """规则监控场景方案解析"""
        return cls.resolve_assets_plan(
            source_type="rule_monitor",
            source_name=rule.name,
            source_path=rule.watch_path,
            target_root=rule.target_dir or "D:/归档备份",
            organize_mode=rule.organize_mode or "comprehensive",
            propose_only=rule.propose_only,
            settled_files=settled_files,
            now=now
        )

    @classmethod
    def resolve_scheduled_task_plan(
        cls,
        task: ScheduledTask,
        scanned_files: List[Dict[str, Any]],
        now: float
    ) -> Tuple[ProposedPlan, bool]:
        """计划任务场景方案解析"""
        return cls.resolve_assets_plan(
            source_type="scheduled_task",
            source_name=task.name,
            source_path=task.target_path,
            target_root=task.target_dir or "D:/归档备份",
            organize_mode=task.organize_mode or "comprehensive",
            propose_only=task.propose_only,
            settled_files=scanned_files,
            now=now
        )

    @classmethod
    def resolve_quick_organize_plan(
        cls,
        title: str,
        target_dir: str,
        dest_root: str,
        scanned_files: List[Dict[str, Any]],
        organize_mode: str = "comprehensive"
    ) -> ProposedPlan:
        """快速整理场景方案解析"""
        import time
        plan, _ = cls.resolve_assets_plan(
            source_type="quick_organize",
            source_name=title,
            source_path=target_dir,
            target_root=dest_root or "D:/归档备份",
            organize_mode=organize_mode,
            propose_only=True,
            settled_files=scanned_files,
            now=time.time()
        )
        return plan
