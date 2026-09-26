with open('app/core/ai_service.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.rstrip() == '                return grouped_units':
        new_lines.append('        return grouped_units\n')
    else:
        new_lines.append(line)

with open('app/core/ai_service.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
