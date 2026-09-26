import re

with open('app/ui/components/organize_dialog.py', 'r', encoding='utf-8') as f:
    content = f.read()

bad = '''        self.archive_worker.progress_signal.connect(self.on_archive_progress)
        self.archive_worker.finished_signal.connect(self.on_archive_finished)
        self.archive_worker.start()'''
good = '''        from app.core.task_manager import global_task_manager, TaskType
        self.archive_task = global_task_manager.create_task(
            name=f"批量归档 ({len(selected_file_items)} 项)",
            task_type=TaskType.MIGRATION,
            worker=self.archive_worker
        )
        self.archive_worker.progress_signal.connect(self.on_archive_progress)
        self.archive_worker.finished_signal.connect(self.on_archive_finished)
        self.archive_worker.start()'''

content = content.replace(bad, good)

with open('app/ui/components/organize_dialog.py', 'w', encoding='utf-8') as f:
    f.write(content)
