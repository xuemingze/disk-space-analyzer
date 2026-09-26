import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Delete on_tree_item_changed
content = re.sub(
    r'    def on_tree_item_changed\(self, item: QTreeWidgetItem, column: int\):.*?    def _set_all_checked_state',
    '    def _set_all_checked_state',
    content,
    flags=re.DOTALL
)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
