import re

with open('app/core/ai_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_classify = False
for i, line in enumerate(lines):
    if 'def classify_files_with_ai' in line:
        in_classify = True
    
    if in_classify and 'system_prompt =' in line:
        print('Found system_prompt at line:', i+1)
        for j in range(i, i+30):
            if j < len(lines):
                print(lines[j].strip())
        break
