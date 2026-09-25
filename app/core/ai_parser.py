import re
from typing import Dict

class AIReportParser:
    @staticmethod
    def extract_sections(markdown_text: str) -> Dict[str, str]:
        sections = {
            "general": "",
            "large_files": "",
            "redundant_files": "",
            "suggestions": "",
            "action_list": ""
        }
        
        if not markdown_text:
            return sections
            
        lines = markdown_text.splitlines()
        current_section = "general"
        
        for line in lines:
            line_stripped = line.strip()
            # Try to match headings
            if re.match(r'^#+\s+.*(大文件|Top).*', line_stripped, re.IGNORECASE):
                current_section = "large_files"
            elif re.match(r'^#+\s+.*(重复|冗余|浪费).*', line_stripped, re.IGNORECASE):
                current_section = "redundant_files"
            elif re.match(r'^#+\s+.*(建议|治理|清理).*', line_stripped, re.IGNORECASE):
                current_section = "suggestions"
            elif re.match(r'^#+\s+.*(清单|执行).*', line_stripped, re.IGNORECASE):
                current_section = "action_list"
            elif re.match(r'^#+\s+.*(现状|健康度|构成|特征).*', line_stripped, re.IGNORECASE):
                current_section = "general"
                
            sections[current_section] += line + "\n"
            
        return sections
