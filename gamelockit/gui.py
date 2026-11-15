"""PyQt6 任务进度窗口；通过共享工作区观察和控制 CLI 任务。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from PyQt6.QtCore import QThread, QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QLayout, QVBoxLayout, QWidget,
)

from . import progress
from .project import Workspace

STATES = {'running': '处理中', 'pausing': '暂停中，等待当前批次完成', 'paused': '已暂停',
          'cancelling': '正在取消', 'cancelled': '已取消', 'complete': '已完成', 'failed': '失败，需要处理',
          'blocked': '需要处理', 'interrupted': '进程已退出，任务中断', 'batch_finished': '批次已提交',
          'rate_limited': '服务限流，等待重试', 'global_cooldown': '等待服务恢复'}
STYLE = """
QWidget { background: #f1f5f9; color: #0f172a; font-family: 'Microsoft YaHei UI', 'Noto Sans CJK SC'; font-size: 14px; }
QMainWindow { background: #f1f5f9; }
QLabel { background: transparent; min-height: 20px; }
QLabel#title { font-size: 22px; font-weight: 600; min-height: 30px; }
QLabel#phase { font-size: 20px; font-weight: 600; min-height: 28px; }
QLabel#muted, QLabel#footer { color: #475569; }
QLabel#notice { color: #9f1239; }
QFrame#panel { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; }
QPushButton { background: #f8fafc; border: 1px solid #94a3b8; border-radius: 6px; padding: 8px 16px; min-height: 26px; }
QPushButton:hover { background: #e2e8f0; }
QPushButton:pressed { background: #cbd5e1; }
QPushButton:focus { border: 2px solid #0f766e; }
QPushButton:disabled { color: #64748b; background: #e2e8f0; border-color: #cbd5e1; }
QPushButton#primary { color: #ffffff; background: #0f766e; border-color: #0f766e; }
QPushButton#primary:hover { background: #115e59; }
QPushButton#primary:disabled { color: #64748b; background: #e2e8f0; border-color: #cbd5e1; }
QPushButton#cancel { color: #9f1239; }
QPushButton#cancel:disabled { color: #64748b; }
QProgressBar { background: #e2e8f0; border: none; border-radius: 4px; min-height: 12px; max-height: 12px; }
QProgressBar::chunk { background: #0f766e; border-radius: 4px; }
QTableWidget { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; gridline-color: #e2e8f0; selection-background-color: #ccfbf1; selection-color: #0f172a; }
QHeaderView::section { background: #e2e8f0; color: #334155; border: none; padding: 10px; font-weight: 600; }
QTableWidget::item { padding: 8px; }
QPlainTextEdit { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 6px; padding: 8px; }
"""


class SnapshotReader(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, root, parent):
        super().__init__(parent)
        self.root = root

    def run(self):
        try:
            self.ready.emit(progress.snapshot(self.root))
        except (OSError, ValueError, KeyError, TypeError, progress.sqlite3.Error) as exc:
            self.failed.emit(str(exc))


def label(text='', name=None):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
    if name:
        widget.setObjectName(name)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


class ProgressWindow(QMainWindow):
    def __init__(self, root=None):
        super().__init__()
        self.root = None
        self.data = None
        self.reader = None
        self.loaded = False
        self.launching_until = 0
        self.setWindowTitle('game-loc-kit · 汉化进度')
        self.resize(980, 760)
        self.setMinimumSize(640, 620)
        self.setStyleSheet(STYLE)
        central = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(central)
        self.setCentralWidget(scroll)
        layout = QVBoxLayout(central)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(label('汉化任务', 'title'))
        top.addStretch()
        self.choose_button = QPushButton('选择工作区')
        self.choose_button.clicked.connect(self.choose_workspace)
        top.addWidget(self.choose_button)
        layout.addLayout(top)
        self.workspace_label = label('请选择 AI 正在使用的汉化工作区。', 'muted')
        self.workspace_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.workspace_label)

        panel = QFrame()
        panel.setObjectName('panel')
        panel.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)
        self.phase_label = label('尚未打开工作区', 'phase')
        self.state_label = label('打开后会自动同步 AI 的任务进度。', 'muted')
        panel_layout.addWidget(self.phase_label)
        panel_layout.addWidget(self.state_label)
        self.activity_bar = QProgressBar()
        self.activity_bar.setRange(0, 0)
        self.activity_bar.setAccessibleName('当前阶段正在处理，暂无可测量的百分比')
        self.activity_bar.setTextVisible(False)
        self.activity_bar.hide()
        panel_layout.addWidget(self.activity_bar)
        self.translation_label = label('翻译进度：尚无数据')
        self.translation_bar = QProgressBar()
        self.translation_bar.setAccessibleName('已放行文本的翻译进度')
        self.translation_bar.setTextVisible(False)
        self.translation_bar.setRange(0, 1)
        panel_layout.addWidget(self.translation_label)
        panel_layout.addWidget(self.translation_bar)
        self.counts_label = label('提取与审核数量将在这里显示。', 'muted')
        panel_layout.addWidget(self.counts_label)
        layout.addWidget(panel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.pause_button = QPushButton('暂停')
        self.pause_button.setToolTip('当前翻译批次完成后暂停，不丢弃已提交的译文。')
        self.resume_button = QPushButton('继续翻译')
        self.resume_button.setObjectName('primary')
        self.resume_button.setToolTip('继续未完成的翻译；需要时会启动已配置的 AI Agent。')
        self.cancel_button = QPushButton('取消任务')
        self.cancel_button.setObjectName('cancel')
        self.cancel_button.setToolTip('停止翻译进程，保留已提交译文；未提交的当前批次稍后重新领取。')
        for button, action in ((self.pause_button, 'pause'), (self.resume_button, 'resume'), (self.cancel_button, 'cancel')):
            button.setEnabled(False)
            button.clicked.connect(lambda checked=False, a=action: self.act(a))
            actions.addWidget(button)
        actions.addStretch()
        layout.addLayout(actions)
        self.notice = label('', 'notice')
        self.notice.setAccessibleName('任务提示与错误')
        self.notice.hide()
        layout.addWidget(self.notice)

        layout.addWidget(label('翻译工作进程'))
        self.workers = QTableWidget(0, 3)
        self.workers.setHorizontalHeaderLabels(['工作进程', '状态', '本批已接受'])
        self.workers.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.workers.verticalHeader().hide()
        self.workers.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.workers.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.workers.setMinimumHeight(128)
        self.workers.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.workers.setAccessibleName('翻译工作进程状态')
        layout.addWidget(self.workers, 1)

        links = QHBoxLayout()
        self.folder_button = QPushButton('打开工作区')
        self.folder_button.clicked.connect(lambda: self.open_folder(self.root))
        self.output_button = QPushButton('打开输出目录')
        self.output_button.clicked.connect(lambda: self.open_folder(self.data.get('output') if self.data else None))
        self.logs_button = QPushButton('查看日志目录')
        self.logs_button.clicked.connect(lambda: self.open_folder(Path(self.root) / 'work' if self.root else None))
        for button in (self.folder_button, self.output_button, self.logs_button):
            button.setEnabled(False)
            links.addWidget(button)
        layout.addLayout(links)
        self.details_button = QPushButton('展开任务记录')
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self.toggle_details)
        layout.addWidget(self.details_button)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(160)
        self.details.setAccessibleName('任务记录与错误详情')
        self.details.hide()
        layout.addWidget(self.details)
        self.footer = label('每 1 秒刷新 · 关闭窗口后，AI 任务继续运行。', 'footer')
        layout.addWidget(self.footer)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        if root:
            self.set_workspace(root)

    def choose_workspace(self):
        root = QFileDialog.getExistingDirectory(self, '选择包含 glk.json 的汉化工作区', str(self.root or Path.cwd()))
        if root:
            self.set_workspace(root)

    def set_workspace(self, root):
        try:
            ws = Workspace(root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.show_error(str(exc))
            return
        self.root = ws.root
        self.loaded = False
        self.data = None
        self.workspace_label.setText(str(self.root))
        self.phase_label.setText('正在读取工作区')
        self.state_label.setText('正在同步任务状态…')
        self.refresh()

    def refresh(self):
        if not self.root or self.reader is not None:
            return
        self.reader = SnapshotReader(self.root, self)
        self.reader.ready.connect(self.render)
        self.reader.failed.connect(self.read_error)
        self.reader.finished.connect(self.reader_finished)
        self.reader.finished.connect(self.reader.deleteLater)
        self.reader.start()

    def reader_finished(self):
        self.reader = None

    def read_error(self, message):
        self.show_error('暂时无法读取进度，将自动重试：' + message)
        self.state_label.setText('数据未更新，请勿将上次显示的进度当作当前状态。')
        for button in (self.pause_button, self.resume_button, self.cancel_button):
            button.setEnabled(False)

    def render(self, data):
        if Path(data['workspace']) != self.root:
            return
        self.loaded = True
        self.data = data
        counts, task = data['counts'], data['task']
        command = task.get('command') if task else None
        state = task.get('state') if task else None
        phase = progress.COMMANDS.get(command, '等待 AI 执行任务')
        self.phase_label.setText(phase)
        self.activity_bar.setVisible(bool(command != 'translate' and state in progress.ACTIVE_STATES))
        elapsed = max(0, int((task.get('ended') or time.time()) - task['started'])) if task else 0
        status = STATES.get(state, '工作区已就绪')
        self.state_label.setText(f'{status} · {data["engine"]}' + (f' · 耗时 {elapsed // 60} 分 {elapsed % 60} 秒' if task else ''))
        released, done = counts['released'], counts['translated']
        self.translation_bar.setRange(0, max(1, released))
        self.translation_bar.setValue(done)
        percent = f' · {done / released:.0%}' if released else ''
        self.translation_label.setText(f'已放行文本：已翻译 {done:,} / {released:,} 条{percent} · 剩余 {counts["pending_translation"]:,} 条')
        self.counts_label.setText(f'已提取 {counts["total"]:,} 条 · 待用途审核 {counts["pending_audit"]:,} 条 · 待复核 {counts["quarantined"]:,} 条 · 术语冲突 {counts["glossary_conflicts"]:,} 项')
        active = command == 'translate' and state in progress.ACTIVE_STATES
        other_active = any(t['command'] != 'translate' and t.get('state') in progress.ACTIVE_STATES for t in data['history'])
        launching = time.monotonic() < self.launching_until
        self.pause_button.setEnabled(active and state == 'running')
        self.cancel_button.setEnabled(active and state != 'cancelling')
        self.resume_button.setEnabled(not launching and not other_active and state != 'cancelling' and
                                      ((active and state in ('paused', 'pausing')) or (not active and counts['pending_translation'] > 0)))
        self.resume_button.setText('继续翻译' if active or command == 'translate' else '开始翻译')
        messages = list(data['warnings'])
        if task and task.get('error'):
            messages.append(task['error'])
        if counts['pending_audit']:
            messages.append('仍有文本等待 AI 完成用途审核；翻译比例只计算已放行文本。')
        if counts['quarantined'] or counts['glossary_conflicts']:
            messages.append('请让 AI 处理待复核条目和术语冲突，再执行构建。')
        if other_active:
            messages.append('当前步骤正在处理文件，完成后可继续翻译。')
        if state == 'paused':
            messages.append('已提交译文会保留；点击“继续翻译”恢复。')
        self.notice.setText('\n'.join(messages))
        self.notice.setVisible(bool(messages))
        rows = data['workers']
        self.workers.setRowCount(max(1, len(rows)))
        if not rows:
            rows = [{'worker': '尚无工作进程', 'state': '等待翻译任务', 'accepted': '—'}]
        for index, row in enumerate(rows):
            worker_state = STATES.get(row.get('state'), str(row.get('state', '未知')))
            if task and row.get('updated', 0) < task.get('started', 0):
                worker_state += '（上次记录）'
            elif not active and row.get('state') in ('running', 'paused', 'global_cooldown', 'rate_limited'):
                worker_state += '（进程记录，非实时）'
            values = (row['worker'], worker_state, str(row.get('accepted', '—')))
            for col, value in enumerate(values):
                self.workers.setItem(index, col, QTableWidgetItem(value))
        lines = []
        for item in data['history']:
            stamp = time.strftime('%m-%d %H:%M:%S', time.localtime(item.get('started', 0)))
            lines.append(f'{stamp}  {progress.COMMANDS.get(item["command"], item["command"])}  {STATES.get(item.get("state"), "未知")}')
            if item.get('error'):
                lines.append('  ' + item['error'])
            if item.get('details'):
                lines.append(json.dumps(item['details'], ensure_ascii=False, indent=2))
        self.details.setPlainText('\n'.join(lines) or '尚无任务记录。AI 执行新版 CLI 命令后会自动记录。')
        self.folder_button.setEnabled(True)
        self.output_button.setEnabled(bool(data['output']))
        self.logs_button.setEnabled((self.root / 'work').is_dir())
        self.footer.setText(f'更新于 {time.strftime("%H:%M:%S")} · 每 1 秒刷新 · 关闭窗口不停止任务')

    def show_error(self, message):
        self.notice.setText(message)
        self.notice.show()

    def act(self, action):
        if not self.root:
            return
        try:
            if progress.control(self.root, action):
                self.start_translation()
            self.refresh()
        except (OSError, ValueError, RuntimeError, KeyError, progress.sqlite3.Error) as exc:
            self.show_error(str(exc))

    def start_translation(self):
        ws = Workspace(self.root)
        ws.path('work').mkdir(exist_ok=True)
        executable = Path(sys.executable)
        if executable.stem.lower() == 'pythonw':
            executable = executable.with_name('python.exe')
        env = dict(os.environ)
        env['PYTHONPATH'] = os.pathsep.join(filter(None, [str(Path(__file__).resolve().parent.parent), env.get('PYTHONPATH')]))
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        path = ws.path('work', f'gui-translate-{time.time_ns()}.log')
        with path.open('w', encoding='utf-8') as stream:
            subprocess.Popen([str(executable), '-m', 'gamelockit', '--ws', str(self.root), 'translate'],
                             cwd=self.root, env=env, stdout=stream, stderr=subprocess.STDOUT, creationflags=flags)
        self.launching_until = time.monotonic() + 3
        self.resume_button.setEnabled(False)
        self.state_label.setText('正在启动翻译…')

    def open_folder(self, path):
        if not path or not Path(path).is_dir():
            self.show_error('目录尚未生成或已被移动。')
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_error(f'无法打开目录，请手动访问：{path}')

    def toggle_details(self, expanded):
        self.details.setVisible(expanded)
        self.details_button.setText('收起任务记录' if expanded else '展开任务记录')

    def closeEvent(self, event):
        self.timer.stop()
        if self.reader:
            self.reader.wait()
        event.accept()


def launch(root=None):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setApplicationName('game-loc-kit')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = ProgressWindow(root)
    window.show()
    return app.exec()


def main():
    try:
        return launch(sys.argv[1] if len(sys.argv) > 1 else None)
    except (OSError, ValueError) as exc:
        QApplication.instance() or QApplication([])
        QMessageBox.critical(None, '进度窗口启动失败', str(exc))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
