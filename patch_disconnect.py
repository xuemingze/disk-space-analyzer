with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    'self.tree.itemExpanded.disconnect(self._on_item_expanded)',
    'try:\n            self.tree.itemExpanded.disconnect(self._on_item_expanded)\n        except RuntimeError:\n            pass'
)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
