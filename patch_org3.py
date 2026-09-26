import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad_indent_1 = '''            if u_data.get("type") == "group":
                  g_info = u_data.get("data", {})
              else:
                  p = item.parent()
                  p_data = p.data(0, Qt.UserRole) if p else {}
                  g_info = p_data.get("data", {})'''
good_indent_1 = '''            if u_data.get("type") == "group":
                g_info = u_data.get("data", {})
            else:
                p = item.parent()
                p_data = p.data(0, Qt.UserRole) if p else {}
                g_info = p_data.get("data", {})'''

content = content.replace(bad_indent_1, good_indent_1)

bad_indent_2 = '''                sub_info = u_data.get("data", {})
                p = item.parent()
                p_data = p.data(0, Qt.UserRole) if p else {}
                group_data = p_data.get("data", {})'''
good_indent_2 = '''                sub_info = u_data.get("data", {})
                p = item.parent()
                p_data = p.data(0, Qt.UserRole) if p else {}
                group_data = p_data.get("data", {})'''
# Actually good_indent_2 is fine, it was just the first one.

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
