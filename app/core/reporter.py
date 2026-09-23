from pathlib import Path
from typing import Dict, Any
from app.core.ai_service import AIService
from app.config import app_config
from app.utils.logger import app_logger


class ReportExporter:
    """
    负责整合扫描数据与 AI 分析结论，导出标准 Markdown 报告
    """

    @staticmethod
    def generate_and_export_report(
        scan_result: Dict[str, Any],
        output_file_path: str,
        use_ai: bool = True
    ) -> bool:
        try:
            llm_cfg = app_config.get("llm", default={})
            base_url = llm_cfg.get("base_url", "")
            api_key = llm_cfg.get("api_key", "")
            model = llm_cfg.get("model", "")

            if use_ai and api_key and base_url:
                app_logger.info(f"正在调用 AI 大模型 ({model}) 生成深度分析报告...")
                report_md = AIService.generate_health_report_with_ai(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    scan_summary=scan_result
                )
            else:
                report_md = AIService._generate_fallback_report(scan_result)

            out_path = Path(output_file_path).resolve()
            out_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(report_md)
                
            app_logger.info(f"成功导出分析报告至: {out_path}")
            return True
        except Exception as e:
            app_logger.error(f"导出分析报告失败: {e}")
            return False
