import sys

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,',
    'from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QProgressDialog,'
)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
