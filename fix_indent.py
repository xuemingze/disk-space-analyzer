import re

with open('app/core/ai_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)

# Wait, let's just do a proper regex replace on the original file
