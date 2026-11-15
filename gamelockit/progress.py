"""CLI 与 GUI 共享的任务记录、只读进度快照和协作式翻译控制。"""
from contextlib import closing
from contextvars import ContextVar
import ctypes
import json
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .project import Workspace, read_json, write_json

COMMANDS = {'extract': '提取文本', 'audit': '用途审核', 'import': '导入译文', 'translate': '翻译',
            'check': '质量校验', 'build': '构建副本', 'shots': '画面检查', 'release': '生成发布目录'}
ACTIVE_STATES = {'running', 'pausing', 'paused', 'cancelling'}
CURRENT_TASK = ContextVar('glk_task', default=None)


def record_result(value):
    task = CURRENT_TASK.get()
    if task is not None and isinstance(value, dict):
        task.data['details'] = {key: value[key] for key in ('ok', 'problems', 'error', 'warning', 'residuals', 'ocr_errors') if key in value}
        if value.get('out'):
            task.data['output'] = str(Path(value['out']).resolve())


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5
        try:
            code = wintypes.DWORD()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


class Task:
    """每个顶层 CLI 操作独立记录；翻译锁防止多个窗口重复启动调度。"""
    def __init__(self, ws, command, output=None):
        self.ws = ws
        self.command = command
        self.path = ws.path('.glk', 'tasks', f'{uuid.uuid4().hex}.json')
        self.lock = ws.path('.glk', 'translate.lock')
        self.data = {'command': command, 'state': 'running', 'pid': os.getpid(), 'started': time.time(),
                     'output': str(Path(output).resolve()) if output else None}
        self.stop = threading.Event()
        self.thread = None
        self.result = 0

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.command == 'translate':
            # 残留锁只在所属进程已经退出时回收。
            for _ in range(2):
                try:
                    fd = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                        json.dump({'pid': os.getpid()}, stream)
                    break
                except FileExistsError:
                    try:
                        pid = read_json(self.lock)['pid']
                    except (OSError, ValueError, KeyError, TypeError):
                        raise RuntimeError('翻译锁正在写入或已损坏，请确认没有翻译进程后检查 .glk/translate.lock') from None
                    if process_alive(pid):
                        raise RuntimeError('此工作区已有翻译任务运行，请在进度窗口中查看或继续')
                    self.lock.unlink(missing_ok=True)
            else:
                raise RuntimeError('无法取得翻译锁，请稍后重试')
        try:
            self._save()
            self.thread = threading.Thread(target=self._heartbeat, daemon=True)
            self.thread.start()
        except BaseException:
            if self.command == 'translate':
                self.lock.unlink(missing_ok=True)
            raise
        self.token = CURRENT_TASK.set(self)
        return self

    def _save(self):
        self.data['updated'] = time.time()
        write_json(self.path, dict(self.data))

    def _heartbeat(self):
        while not self.stop.wait(2):
            try:
                self._save()
            except OSError:
                # 磁盘故障不应使已经运行的汉化任务在后台线程中崩溃。
                return

    def finish(self, code, error=None):
        self.result = code or 0
        if error:
            self.data['error'] = error

    def __exit__(self, kind, exc, traceback):
        CURRENT_TASK.reset(self.token)
        self.stop.set()
        if self.thread:
            self.thread.join()
        state = 'failed' if kind or self.result else 'complete'
        if kind is KeyboardInterrupt or (self.command == 'translate' and self.ws.stop_file.exists()):
            state = 'cancelled'
        elif self.command == 'translate' and not kind and not self.result:
            try:
                pending = _counts(self.ws)['pending_translation']
            except sqlite3.Error:
                state = 'blocked'
                self.data['error'] = '翻译进程已结束，暂时无法读取剩余数量，请刷新后确认。'
            else:
                if pending:
                    state = 'blocked'
                    self.data['error'] = '仍有待翻译条目，请检查工作进程记录后继续。'
        self.data.update(state=state, ended=time.time())
        if exc:
            self.data['error'] = str(exc)
        try:
            self._save()
        finally:
            if self.command == 'translate':
                self.lock.unlink(missing_ok=True)


def _counts(ws):
    result = dict(total=0, pending_audit=0, released=0, translated=0, pending_translation=0,
                  leased=0, quarantined=0, glossary_conflicts=0)
    if not ws.db.exists():
        return result
    # 不使用 catalog.connection：它会建表并取得写锁，监视器必须只读。
    with closing(sqlite3.connect(ws.db.as_uri() + '?mode=ro', uri=True, timeout=.3)) as con:
        con.execute('BEGIN')
        row = con.execute("""SELECT count(*), coalesce(sum(usage='pending'),0), coalesce(sum(released=1),0),
            coalesce(sum(released=1 AND target IS NOT NULL),0),
            coalesce(sum(released=1 AND target IS NULL AND worker IS NOT NULL AND expires>?),0) FROM items""", (time.time(),)).fetchone()
        result.update(zip(('total', 'pending_audit', 'released', 'translated', 'leased'), row))
        result['pending_translation'] = result['released'] - result['translated']
        result['quarantined'] = con.execute('SELECT count(*) FROM quarantine').fetchone()[0]
        result['glossary_conflicts'] = con.execute('SELECT count(*) FROM glossary_conflicts').fetchone()[0]
    return result


def snapshot(root):
    ws = Workspace(root)
    warnings, tasks, workers = [], [], []
    counts = _counts(ws)
    for path in ws.path('.glk', 'tasks').glob('*.json'):
        try:
            item = read_json(path)
            if not isinstance(item, dict) or item.get('command') not in COMMANDS:
                raise ValueError('任务记录格式无效')
            if item.get('state') in ACTIVE_STATES and not process_alive(item.get('pid')):
                item['state'] = 'interrupted'
            tasks.append(item)
        except (OSError, ValueError, TypeError):
            warnings.append(f'无法读取任务记录：{path.name}')
    tasks.sort(key=lambda t: t.get('started', 0), reverse=True)
    for path in sorted(ws.path('work').glob('worker-*/status.json')):
        try:
            item = read_json(path)
            if not isinstance(item, dict):
                raise ValueError('工作进程记录格式无效')
            item['worker'] = path.parent.name
            item['updated'] = path.stat().st_mtime
            workers.append(item)
        except (OSError, ValueError, TypeError):
            warnings.append(f'无法读取工作进程记录：{path.parent.name}')
    active = [t for t in tasks if t.get('state') in ACTIVE_STATES]
    current = dict((active or tasks)[0]) if tasks else None
    if current and current.get('command') == 'translate' and current.get('state') in ACTIVE_STATES:
        if ws.stop_file.exists():
            current['state'] = 'cancelling'
        elif ws.path('PAUSE').exists():
            current_workers = [w for w in workers if w['updated'] >= current['started']]
            current['state'] = 'pausing' if any(w.get('state') == 'running' for w in current_workers) else 'paused'
    outputs = [t['output'] for t in tasks if t.get('output') and t.get('state') == 'complete' and Path(t['output']).is_dir()]
    return {'workspace': str(ws.root), 'game': str(ws.game_dir), 'engine': ws.engine, 'counts': counts,
            'task': current, 'history': tasks[:30], 'workers': workers, 'warnings': warnings,
            'output': outputs[0] if outputs else str(ws.path('build')) if ws.path('build').is_dir() else None}


def control(root, action):
    """返回 True 表示继续操作需要启动新的翻译调度；本函数不启动进程。"""
    if action not in ('pause', 'resume', 'cancel'):
        raise ValueError('未知控制操作')
    ws = Workspace(root)
    data = snapshot(ws.root)
    translations = [t for t in data['history'] if t.get('command') == 'translate' and t.get('state') in ACTIVE_STATES]
    active = bool(translations)
    if action != 'resume' and not active:
        raise ValueError('当前没有可控制的翻译任务')
    if action == 'pause':
        ws.path('PAUSE').touch()
    elif action == 'cancel':
        ws.stop_file.touch()
        ws.path('PAUSE').unlink(missing_ok=True)
    else:
        if ws.stop_file.exists() and active:
            raise ValueError('正在取消，请等待翻译进程退出后再继续')
        if not active and not data['counts']['pending_translation']:
            raise ValueError('没有待翻译条目，请先完成提取与用途审核')
        ws.path('PAUSE').unlink(missing_ok=True)
        ws.stop_file.unlink(missing_ok=True)
        return not active
    return False
