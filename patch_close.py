import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

close_event_code = '''
    def closeEvent(self, event):
        if hasattr(self, 'archive_worker') and self.archive_worker and self.archive_worker.isRunning():
            try:
                self.archive_worker.progress_signal.disconnect(self.on_archive_progress)
                self.archive_worker.finished_signal.disconnect(self.on_archive_finished)
            except RuntimeError:
                pass
        super().closeEvent(event)
'''

# Insert closeEvent before init_ui
content = content.replace('    def init_ui(self):', close_event_code + '\n    def init_ui(self):')

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
