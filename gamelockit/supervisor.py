"""翻译调度：固定工作槽轮流领取批次，限制同时运行的子 Agent 数，遇限流全局退避。

每批启动一个全新上下文的子 Agent（命令模板见工作区配置 translator.command），
子 Agent 按 work/WORKER_INSTRUCTIONS.md 自行 claim → 翻译 → submit。
只使用 AI 子 Agent 翻译，不调用机器翻译。
"""
from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import os
import subprocess
import time
import uuid
from threading import BoundedSemaphore, Lock

from . import catalog
from .project import write_json


def retry_delay(attempt):
    return min(300, 30 * 2 ** min(max(attempt - 1, 0), 4))


def log_has_marker(path, markers):
    """只在错误行里找限流标记，避免译文内容恰好含这些词时误判。"""
    markers = [m.lower() for m in markers]
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return False
    for line in lines:
        try:
            message = json.loads(line).get('message', {})
            text = str(message.get('errorMessage', '')) if isinstance(message, dict) and message.get('stopReason') == 'error' else ''
        except (ValueError, AttributeError):
            text = line if 'error' in line.lower() else ''
        if text and any(m in text.lower() for m in markers):
            return True
    return False


class Supervisor:
    def __init__(self, ws, prompt_for):
        cfg = ws.config['translator']
        self.ws = ws
        self.prompt_for = prompt_for
        self.command = cfg['command']
        self.slots = int(cfg['slots'])
        self.batch = int(cfg['batch'])
        self.markers = cfg['transient_markers']
        self.limit = BoundedSemaphore(max(1, int(cfg['max_concurrency'])))
        self.lock = Lock()
        self.cooldown_until = 0.0
        self.streak = 0

    def stopped(self):
        return self.ws.stop_file.exists()

    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.stopped() and time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline - time.monotonic())))

    def args(self, worker):
        prompt = self.prompt_for(worker)
        args = [part.replace('{prompt}', prompt).replace('{worker}', worker) for part in self.command]
        # npm 安装的 CLI 在 Windows 上是 .cmd 启动脚本，Popen 不按 PATHEXT 查找，需先解析成完整路径
        args[0] = shutil.which(args[0]) or args[0]
        return args

    def run_agent(self, worker, folder, log):
        while not self.stopped() and not self.limit.acquire(timeout=1):
            pass
        if self.stopped():
            return None
        try:
            env = {k: v for k, v in os.environ.items() if not k.startswith(('PEBREL_', 'PI_SESSION_'))}
            with log.open('w', encoding='utf-8') as out:
                while True:
                    if self.stopped():
                        return None
                    with self.lock:
                        remaining = self.cooldown_until - time.monotonic()
                        if remaining <= 0:
                            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                            child = subprocess.Popen(self.args(worker), cwd=self.ws.root, env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=flags)
                            break
                    write_json(folder / 'status.json', {'state': 'global_cooldown', 'retry_seconds': round(remaining, 1)})
                    self.wait(min(remaining, 1))
                write_json(folder / 'status.json', {'state': 'running', 'pid': child.pid, 'log': str(log), 'started': time.time()})
                try:
                    while child.poll() is None:
                        if self.stopped():
                            child.terminate()
                            break
                        time.sleep(2)
                    return child.wait(timeout=30)
                except BaseException:
                    child.kill()
                    child.wait()
                    raise
        finally:
            if log.exists() and log_has_marker(log, self.markers) and not self.stopped():
                with self.lock:
                    self.streak += 1
                    self.cooldown_until = max(self.cooldown_until, time.monotonic() + retry_delay(self.streak))
            else:
                with self.lock:
                    if time.monotonic() >= self.cooldown_until:
                        self.streak = 0
            self.limit.release()

    def worker(self, name):
        folder = self.ws.path('work', name)
        folder.mkdir(parents=True, exist_ok=True)
        failures = 0
        while not self.stopped():
            st = catalog.status(self.ws.db)
            if st['pending_translation'] == 0:
                write_json(folder / 'status.json', {'state': 'complete'})
                return
            if st['pending_translation'] == st['leased'] and not self._owns(name):
                time.sleep(5)
                continue
            before = self._done(name)
            log = folder / f'agent-{int(time.time())}.log'
            code = self.run_agent(name, folder, log)
            if code is None:
                break
            blocked = folder / 'blocked.json'
            if blocked.exists():
                catalog.quarantine(self.ws.db, name, json.loads(blocked.read_text(encoding='utf-8')))
                (folder / 'review').mkdir(exist_ok=True)
                blocked.replace(folder / 'review' / f'{uuid.uuid4().hex}.json')
            catalog.release(self.ws.db, name)
            accepted = self._done(name) - before
            if log_has_marker(log, self.markers):
                write_json(folder / 'status.json', {'state': 'rate_limited', 'accepted': accepted})
                continue
            failures = failures + 1 if accepted == 0 else 0
            write_json(folder / 'status.json', {'state': 'batch_finished', 'exit_code': code, 'accepted': accepted, 'failures': failures})
            if failures >= 3:
                write_json(folder / 'status.json', {'state': 'blocked', 'exit_code': code, 'log': str(log)})
                return
            if failures:
                self.wait(10)
        catalog.release(self.ws.db, name)

    def _done(self, name):
        with catalog.connection(self.ws.db) as con:
            return con.execute('SELECT count(*) FROM items WHERE worker=? AND target IS NOT NULL', (name,)).fetchone()[0]

    def _owns(self, name):
        with catalog.connection(self.ws.db) as con:
            return con.execute('SELECT 1 FROM items WHERE worker=? AND target IS NULL LIMIT 1', (name,)).fetchone() is not None

    def run(self):
        if self.stopped():
            raise RuntimeError(f'存在 STOP 标记（{self.ws.stop_file}），删除后再启动')
        names = [f'worker-{n}' for n in range(1, self.slots + 1)]
        with ThreadPoolExecutor(max_workers=self.slots) as pool:
            list(pool.map(self.worker, names))
        return catalog.status(self.ws.db)
