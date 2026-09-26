import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad = '''        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeToContents)'''
good = '''        header.setSectionResizeMode(5, QHeaderView.Interactive)
        self.tree.setColumnWidth(5, 80)
        header.setSectionResizeMode(6, QHeaderView.Interactive)
        self.tree.setColumnWidth(6, 60)
        header.setSectionResizeMode(7, QHeaderView.Interactive)
        self.tree.setColumnWidth(7, 80)
        header.setSectionResizeMode(8, QHeaderView.Interactive)
        self.tree.setColumnWidth(8, 80)'''

content = content.replace(bad, good)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
