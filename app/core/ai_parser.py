import re
from typing import Dict

class AIReportParser:
    @staticmethod
    def extract_sections(markdown_text: str) -> Dict[str, str]:
        sections = {
            "panorama_core_issues": "",
            "panorama_key_observations": "",
            "panorama_redundant_hotspots": "",
            "duplicate_waste": "",
            "duplicate_warning": "",
            "top10_analysis": "",
            "top10_warning": ""
        }
        
        if not markdown_text:
            return sections
            
        lines = markdown_text.splitlines()
        current_section = None
        
        # Regex patterns to tolerate spaces, emojis, and punctuation, updated based on the real report structure
        p_core = re.compile(r'^(#+\s+.*?(磁盘现状与健康度评估|总结与建议).*|^\*\*\s*.*?核心问题.*?\*\*)', re.IGNORECASE)
        p_obs = re.compile(r'^(#+\s+.*?(空间构成与类型特征|核心执行清单).*|^\*\*\s*.*?关键观察.*?\*\*)', re.IGNORECASE)
        p_top10 = re.compile(r'^#+\s+.*?(TOP\s*10\s*大文件).*', re.IGNORECASE)
        p_hotspots = re.compile(r'^#+\s+.*?(大文件与冗余分布|冗余文件分布特征|冗余分布热点).*', re.IGNORECASE)
        p_waste = re.compile(r'^#+\s+.*?(重复文件浪费分析).*', re.IGNORECASE)
        p_warn = re.compile(r'^(#+\s+.*?(分级治理与清理优化建议|不建议清理|风险).*|^\*\*\s*.*?严禁误删警告.*?\*\*)', re.IGNORECASE)
        
        # A generic H1/H2 header or bold line to stop extraction, so it doesn't truncate at H3/H4 sub-sections
        p_stop = re.compile(r'^(#{1,2}\s+|\*\*\s*[^\*]+\s*\*\*$)')
        
        for line in lines:
            line_stripped = line.strip()
            if not line_stripped:
                if current_section:
                    sections[current_section] += "\n"
                continue
                
            matched_new = False
            
            if p_core.match(line_stripped):
                current_section = "panorama_core_issues"
                matched_new = True
            elif p_obs.match(line_stripped):
                current_section = "panorama_key_observations"
                matched_new = True
            elif p_top10.match(line_stripped):
                current_section = "top10_analysis"
                matched_new = True
            elif p_hotspots.match(line_stripped):
                current_section = "panorama_redundant_hotspots"
                matched_new = True
            elif p_waste.match(line_stripped):
                current_section = "duplicate_waste"
                matched_new = True
            elif p_warn.match(line_stripped):
                # Warning can appear multiple times. We assign it to both duplicate and top10 if empty, or just append
                # Actually, the user asked for it in both tabs. Let's just collect all warnings.
                current_section = "duplicate_warning"
                matched_new = True
            elif p_stop.match(line_stripped):
                # Stop accumulating if we hit a new unknown header or bold title
                current_section = None
                
            if current_section:
                # Add the title itself if it's the start
                sections[current_section] += line + "\n"
                # If we are in duplicate_warning, we also mirror it to top10_warning
                if current_section == "duplicate_warning" and matched_new:
                    if "top10_warning" not in sections:
                        sections["top10_warning"] = ""
                if current_section == "duplicate_warning" and not matched_new:
                    sections["top10_warning"] += line + "\n"

        # Mirror the warning title to top10_warning as well
        if sections["duplicate_warning"]:
            sections["top10_warning"] = sections["duplicate_warning"]
            
        return sections
