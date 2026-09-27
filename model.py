from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QBrush, QFont
from pathlib import Path
from app.utils.file_helper import format_size, is_system_critical_path
from typing import List, Dict, Any

class ArchiveTreeModel(QAbstractItemModel):
    stats_updated = Signal(int, int) # selected_count, selected_bytes

    def __init__(self, classification_items, active_categories, parent=None):
        super().__init__(parent)
        self.groups = classification_items
        self.active_categories = active_categories
        
        # Pre-process data
        self.root_items = []
        for i, group in enumerate(self.groups):
            orig_root = group.get('original_root', '')
            risk = group.get('risk_level', '未知风险')
            is_sys = is_system_critical_path(orig_root) if orig_root else False
            conf = float(group.get('confidence', 0.0))
            req_conf = group.get('require_confirmation', True)
            app_name = group.get('app_name', '').lower()
            unrec = not app_name or '未识别' in app_name or '未知' in app_name
            
            default_checked = (not req_conf) and conf >= 0.7 and (not unrec) and (not is_sys)
            
            g_node = {
                'is_group': True,
                'data': group,
                '_idx': i,
                'check_state': Qt.Checked if default_checked else Qt.Unchecked,
                'children': []
            }
            self.root_items.append(g_node)
            
            for j, sub in enumerate(group.get('sub_items', [])):
                f_node = {
                    'is_group': False,
                    'data': sub,
                    '_parent': g_node,
                    '_idx': j,
                    'check_state': g_node['check_state']
                }
                g_node['children'].append(f_node)

    def index(self, row, column, parent=QModelIndex()):
        if not parent.isValid():
            if 0 <= row < len(self.root_items):
                return self.createIndex(row, column, self.root_items[row])
            return QModelIndex()
            
        parent_node = parent.internalPointer()
        if parent_node['is_group']:
            if 0 <= row < len(parent_node['children']):
                return self.createIndex(row, column, parent_node['children'][row])
        return QModelIndex()

    def parent(self, index):
        if not index.isValid(): return QModelIndex()
        node = index.internalPointer()
        if node['is_group']: return QModelIndex()
        p_node = node['_parent']
        return self.createIndex(p_node['_idx'], 0, p_node)

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid(): return len(self.root_items)
        node = parent.internalPointer()
        if node['is_group']: return len(node['children'])
        return 0

    def columnCount(self, parent=QModelIndex()): return 10

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid(): return None
        node = index.internalPointer()
        col = index.column()
        is_g = node['is_group']
        d = node['data']
        
        if role == Qt.DisplayRole:
            if col == 0:
                if is_g:
                    pt = Path(d.get('original_root', ''))
                    return f"📦 {pt.name if pt.name else str(pt)}"
                else:
                    return d.get('relative_path', '')
            elif col == 1:
                if is_g:
                    src = d.get('source', '离线规则')
                    return f"{d.get('app_name', '')} [{src}]"
                return "-"
            elif col == 2:
                if is_g: return d.get('suggested_category', '')
                return node['_parent']['data'].get('effective_category', node['_parent']['data'].get('suggested_category', ''))
            elif col == 3:
                return d.get('target_root', '') if is_g else d.get('target_path', '')
            elif col == 4:
                return d.get('rationale', '') if is_g else "包含在目录单元中"
            elif col == 5:
                if is_g:
                    sz = sum(s.get('size', 0) for s in d.get('sub_items', []))
                    return f"{len(d.get('sub_items', []))} 项 ({format_size(sz)})"
                return format_size(d.get('size', 0))
            elif col == 6:
                return f"{float(d.get('confidence', 0.0))*100:.1f}%" if is_g else "-"
            elif col == 7:
                if is_g: return d.get('risk_level', '未知风险')
                return node['_parent']['data'].get('risk_level', '未知风险')
            elif col == 8:
                return d.get('action', '') if is_g else node['_parent']['data'].get('action', '')
            elif col == 9:
                if is_g: return f"R:{d.get('report_id','-')} | T:{d.get('task_id','-')}"
                p_d = node['_parent']['data']
                return f"R:{p_d.get('report_id','-')} | T:{p_d.get('task_id','-')}"
                
        elif role == Qt.CheckStateRole and col == 0:
            return node['check_state']
            
        elif role == Qt.BackgroundRole:
            if is_g: return QBrush(QColor("#E3F2FD"))
            
        elif role == Qt.ForegroundRole:
            if is_g:
                if col == 1:
                    src = d.get('source', '离线规则')
                    return QBrush(QColor("#38BDF8")) if src == "AI" else QBrush(QColor("#94A3B8"))
                return QBrush(QColor("#000000"))
            if col == 7:
                risk = node['_parent']['data'].get('risk_level', '') if not is_g else d.get('risk_level', '')
                if '低' in risk: return QBrush(QColor("#10B981"))
                if '中' in risk: return QBrush(QColor("#F59E0B"))
                return QBrush(QColor("#EF4444"))
                
        elif role == Qt.FontRole:
            if is_g and col == 1:
                f = QFont()
                f.setBold(True)
                return f
                
        elif role == Qt.TextAlignmentRole:
            if col == 5: return int(Qt.AlignRight | Qt.AlignVCenter)
            if col in (6,7,8): return int(Qt.AlignCenter)
            
        elif role == Qt.ToolTipRole and col == 0:
            return d.get('original_root', '') if is_g else d.get('original_path', '')

        return None

    def flags(self, index):
        if not index.isValid(): return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemIsUserCheckable
        return flags

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid(): return False
        node = index.internalPointer()
        
        if role == Qt.CheckStateRole and index.column() == 0:
            new_state = Qt.CheckState(value)
            node['check_state'] = new_state
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            
            # Cascade to children
            if node['is_group']:
                for i, child in enumerate(node['children']):
                    if child['check_state'] != new_state:
                        child['check_state'] = new_state
                        c_idx = self.index(i, 0, index)
                        self.dataChanged.emit(c_idx, c_idx, [Qt.CheckStateRole])
            else:
                # Update parent
                p_node = node['_parent']
                p_idx = self.parent(index)
                checked = 0
                partial = 0
                for c in p_node['children']:
                    if c['check_state'] == Qt.Checked: checked += 1
                    elif c['check_state'] == Qt.PartiallyChecked: partial += 1
                
                if checked == len(p_node['children']): p_state = Qt.Checked
                elif checked > 0 or partial > 0: p_state = Qt.PartiallyChecked
                else: p_state = Qt.Unchecked
                
                if p_node['check_state'] != p_state:
                    p_node['check_state'] = p_state
                    self.dataChanged.emit(p_idx, p_idx, [Qt.CheckStateRole])
                    
            self._update_stats()
            return True
            
        elif role == Qt.EditRole and index.column() == 2:
            if node['is_group']:
                node['data']['effective_category'] = value
                self.dataChanged.emit(index, index, [Qt.DisplayRole])
                # Update children's display for col 2
                for i in range(len(node['children'])):
                    c_idx = self.index(i, 2, self.index(node['_idx'], 0))
                    self.dataChanged.emit(c_idx, c_idx, [Qt.DisplayRole])
                return True
                
        return False

    def _update_stats(self):
        sel_cnt = 0
        tot_b = 0
        for g in self.root_items:
            for c in g['children']:
                if c['check_state'] == Qt.Checked:
                    sel_cnt += 1
                    tot_b += c['data'].get('size', 0)
        self.stats_updated.emit(sel_cnt, tot_b)
