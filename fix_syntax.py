with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if line.startswith('from PySide6.QtWidgets import QProgressDialog, ('):
        lines[i] = line.replace('from PySide6.QtWidgets import QProgressDialog, (', 'from PySide6.QtWidgets import (\n    QProgressDialog,')
with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
