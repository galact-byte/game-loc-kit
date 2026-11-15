"""进度读取、CLI 任务记录、翻译控制及 Qt 窗口的行为测试。"""
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

from gamelockit import catalog
from gamelockit.adapters.base import Occurrence
from gamelockit.cli import main
from gamelockit.project import Workspace, write_json
from gamelockit.supervisor import Supervisor
from gamelockit.validate import compile_tokens


def progress():
    assert importlib.util.find_spec('gamelockit.progress'), '缺少任务进度与控制模块'
    return importlib.import_module('gamelockit.progress')


@pytest.fixture
def ws(tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    return Workspace.create(tmp_path / '工作区', game, 'rpgmaker')


def test_monitor_does_not_create_database_or_modify_workspace(ws):
    before = sorted(p.relative_to(ws.root) for p in ws.root.rglob('*'))
    snapshot = progress().snapshot(ws.root)
    assert snapshot['counts']['released'] == 0
    assert snapshot['task'] is None
    assert before == sorted(p.relative_to(ws.root) for p in ws.root.rglob('*'))


def test_monitor_counts_live_translations_without_reading_story_text(ws):
    catalog.add_occurrences(ws.db, [Occurrence('秘密の台詞', 'test', '1', '', 'display'),
                                     Occurrence('まだです', 'test', '2', '', 'display'),
                                     Occurrence('識別子', 'test', '3', '', 'unknown')], False)
    task = catalog.claim(ws.db, 'worker-1', 1)
    catalog.submit(ws.db, 'worker-1', task['lease'], [{'id': task['items'][0]['id'], 'target': '秘密台词'}], [], compile_tokens())
    with sqlite3.connect(ws.db) as con:
        con.execute('BEGIN IMMEDIATE')
        snapshot = progress().snapshot(ws.root)
    assert snapshot['counts']['translated'] == 1
    assert snapshot['counts']['pending_translation'] == 1
    assert snapshot['counts']['pending_audit'] == 1
    assert '秘密' not in json.dumps(snapshot, ensure_ascii=False)


def test_task_records_success_failure_and_stale_runs(ws):
    module = progress()
    with module.Task(ws, 'extract') as task:
        assert module.snapshot(ws.root)['task']['state'] == 'running'
        task.finish(0)
    assert module.snapshot(ws.root)['task']['state'] == 'complete'
    with pytest.raises(RuntimeError, match='测试失败'):
        with module.Task(ws, 'build'):
            raise RuntimeError('测试失败')
    snapshot = module.snapshot(ws.root)
    assert snapshot['task']['state'] == 'failed'
    assert snapshot['task']['error'] == '测试失败'
    path = ws.path('.glk', 'tasks', 'stale.json')
    write_json(path, {'id': 'stale', 'command': 'translate', 'state': 'running', 'pid': 0,
                      'started': time.time() + 1, 'updated': time.time()})
    assert module.snapshot(ws.root)['task']['state'] == 'interrupted'


def test_broken_worker_record_is_reported_without_losing_counts(ws):
    ws.path('work', 'worker-1').mkdir(parents=True)
    ws.path('work', 'worker-1', 'status.json').write_text('{', encoding='utf-8')
    snapshot = progress().snapshot(ws.root)
    assert snapshot['counts']['translated'] == 0
    assert snapshot['warnings']


def test_control_rejects_pausing_without_active_translation(ws):
    with pytest.raises(ValueError):
        progress().control(ws.root, 'pause')
    assert not ws.path('PAUSE').exists()


def test_pause_resume_and_cancel_flags_are_shared_with_cli(ws):
    module = progress()
    with module.Task(ws, 'translate') as task:
        module.control(ws.root, 'pause')
        assert ws.path('PAUSE').exists()
        assert not module.control(ws.root, 'resume')
        assert not ws.path('PAUSE').exists()
        module.control(ws.root, 'cancel')
        assert ws.stop_file.exists()
        task.finish(0)
    assert module.snapshot(ws.root)['task']['state'] == 'cancelled'


def test_duplicate_translation_is_rejected_and_lock_is_released(ws):
    module = progress()
    with module.Task(ws, 'translate') as task:
        with pytest.raises(RuntimeError):
            with module.Task(ws, 'translate'):
                pass
        task.finish(0)
    with module.Task(ws, 'translate') as task:
        task.finish(0)


def test_translation_exit_releases_lock_even_if_database_is_busy(ws):
    module = progress()
    catalog.status(ws.db)
    with sqlite3.connect(ws.db) as con:
        con.execute('BEGIN EXCLUSIVE')
        with module.Task(ws, 'translate') as task:
            task.finish(0)
        assert not ws.path('.glk', 'translate.lock').exists()
    assert module.snapshot(ws.root)['task']['state'] == 'blocked'


def test_cli_failure_is_visible_to_monitor(ws, capsys):
    module = progress()
    assert main(['--ws', str(ws.root), 'build', '--no-probe']) == 1
    capsys.readouterr()
    task = module.snapshot(ws.root)['task']
    assert task['command'] == 'build' and task['state'] == 'failed'
    assert task['error']
    assert '完整性清单' in json.dumps(task.get('details'), ensure_ascii=False)


def test_supervisor_waits_while_paused_then_finishes_without_agent(ws):
    ws.path('PAUSE').touch()
    ws.config['translator']['slots'] = 1
    supervisor = Supervisor(ws, lambda _: '')
    errors = []

    def run():
        try:
            supervisor.run()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 3
        path = ws.path('work', 'worker-1', 'status.json')
        while time.monotonic() < deadline:
            if path.exists() and json.loads(path.read_text(encoding='utf-8')).get('state') == 'paused':
                break
            time.sleep(.02)
        assert path.exists() and json.loads(path.read_text(encoding='utf-8'))['state'] == 'paused'
        ws.path('PAUSE').unlink()
        thread.join(3)
        assert not thread.is_alive() and not errors
    finally:
        ws.stop_file.touch()
        thread.join(3)


def test_pause_finishes_current_batch_and_resume_translates_remaining(ws):
    module = progress()
    catalog.add_occurrences(ws.db, [Occurrence(text, 'test', str(i), '', 'display')
                                     for i, text in enumerate(('はい', 'いいえ', 'またね'))], False)
    claimed = ws.path('claimed')
    proceed = ws.path('proceed')
    script = ws.path('fake_agent.py')
    script.write_text(
        'import sys,time\n'
        f'sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})\n'
        'from gamelockit import catalog\n'
        'from gamelockit.project import Workspace\n'
        'from gamelockit.validate import compile_tokens\n'
        f'ws = Workspace({str(ws.root)!r})\n'
        'task = catalog.claim(ws.db, "worker-1", 1)\n'
        'ws.path("claimed").touch()\n'
        'while not ws.path("proceed").exists(): time.sleep(.02)\n'
        'catalog.submit(ws.db, "worker-1", task["lease"], '
        '[{"id": i["id"], "target": "中文"} for i in task["items"]], [], compile_tokens())\n', encoding='utf-8')
    ws.config['translator'].update(command=[sys.executable, str(script)], slots=1, max_concurrency=1)
    errors = []

    def run():
        try:
            Supervisor(ws, lambda _: '').run()
        except BaseException as exc:
            errors.append(exc)

    with module.Task(ws, 'translate') as task:
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not claimed.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert claimed.exists()
            module.control(ws.root, 'pause')
            proceed.touch()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                data = module.snapshot(ws.root)
                if data['task']['state'] == 'paused':
                    break
                time.sleep(.02)
            assert data['task']['state'] == 'paused'
            assert data['counts']['translated'] == 1 and data['counts']['pending_translation'] == 2
            assert not module.control(ws.root, 'resume')
            thread.join(8)
            assert not thread.is_alive() and not errors
            assert catalog.status(ws.db)['translated'] == 3
            task.finish(0)
        finally:
            proceed.touch()
            ws.stop_file.touch()
            thread.join(8)


def test_cancel_stops_agent_descendants_and_releases_leases(ws):
    module = progress()
    catalog.add_occurrences(ws.db, [Occurrence('はい', 'test', '1', '', 'display')], False)
    pid_file = ws.path('child.pid')
    script = ('import subprocess,sys,time,pathlib; '
              'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"]); '
              f'pathlib.Path({str(pid_file)!r}).write_text(str(child.pid)); time.sleep(60)')
    ws.config['translator'].update(command=[sys.executable, '-c', script], slots=1, max_concurrency=1)
    supervisor = Supervisor(ws, lambda _: '')
    errors = []

    def run():
        try:
            supervisor.run()
        except BaseException as exc:
            errors.append(exc)

    with module.Task(ws, 'translate') as task:
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert pid_file.exists()
            pid = int(pid_file.read_text())
            module.control(ws.root, 'cancel')
            thread.join(8)
            assert not thread.is_alive() and not errors
            assert not module.process_alive(pid), '取消后仍有 Agent 子进程残留'
            assert catalog.status(ws.db)['leased'] == 0
            task.finish(0)
        finally:
            ws.stop_file.touch()
            thread.join(8)


def test_qt_window_refreshes_real_data_and_preserves_running_task(ws):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    assert importlib.util.find_spec('gamelockit.gui'), '缺少 Qt 进度窗口'
    from gamelockit.gui import ProgressWindow
    app = QApplication.instance() or QApplication([])
    catalog.add_occurrences(ws.db, [Occurrence('はい', 'test', '1', '', 'display'),
                                     Occurrence('識別子', 'test', '2', '', 'unknown')], False)
    window = ProgressWindow(ws.root)
    window.show()
    deadline = time.monotonic() + 3
    while not window.loaded and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    try:
        assert window.loaded
        assert window.translation_bar.maximum() == 1
        assert window.translation_bar.value() == 0
        app.processEvents()
        assert window.centralWidget().verticalScrollBar().maximum() == 0, '默认尺寸不应把操作按钮推到屏幕外'
        window.resize(640, 620)
        window.details_button.setChecked(True)
        app.processEvents()
        assert window.phase_label.height() >= window.phase_label.fontMetrics().height(), '小窗口裁切了当前阶段文字'
        assert window.translation_label.height() >= window.translation_label.fontMetrics().height(), '小窗口裁切了翻译数量'
        with progress().Task(ws, 'translate') as task:
            window.close()
            app.processEvents()
            assert not ws.stop_file.exists()
            task.finish(0)
    finally:
        window.close()
        app.processEvents()


def test_qt_resume_starts_cli_and_shows_completed_translation(ws):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from gamelockit.gui import ProgressWindow
    app = QApplication.instance() or QApplication([])
    catalog.add_occurrences(ws.db, [Occurrence('はい', 'test', '1', '', 'display')], False)
    script = ('from gamelockit import catalog; from gamelockit.project import Workspace; '
              'from gamelockit.validate import compile_tokens; '
              f'ws=Workspace({str(ws.root)!r}); '
              'task=catalog.claim(ws.db,"worker-1",1); '
              'catalog.submit(ws.db,"worker-1",task["lease"],'
              '[{"id":i["id"],"target":"中文"} for i in task["items"]],[],compile_tokens())')
    ws.config['translator'].update(command=[sys.executable, '-c', script], slots=1, max_concurrency=1)
    ws.save()
    window = ProgressWindow(ws.root)
    window.show()
    try:
        deadline = time.monotonic() + 5
        while not window.loaded and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert window.loaded and window.resume_button.isEnabled()
        window.resume_button.click()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            app.processEvents()
            if window.data and window.data['task'] and window.data['task']['state'] == 'complete':
                break
            time.sleep(.02)
        assert window.data['task']['state'] == 'complete'
        assert window.translation_bar.value() == window.translation_bar.maximum() == 1
        assert not window.resume_button.isEnabled()
        assert not window.pause_button.isEnabled() and not window.cancel_button.isEnabled()
    finally:
        data = progress().snapshot(ws.root)
        if data['task'] and data['task']['state'] in progress().ACTIVE_STATES:
            progress().control(ws.root, 'cancel')
        window.close()
        app.processEvents()
