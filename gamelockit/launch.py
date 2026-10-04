"""启动汉化副本：直接启动或经 Locale Emulator 转区启动，并按 EXE 路径跟踪真正的游戏进程。

转区启动时 LEProc 会先退出、游戏作为另一个进程运行，所以不能用 Popen 的子进程判断存活。
配置（glk.json）：
  "launch": {"locale": "auto" | "ja" | "none", "locale_emulator": "LEProc.exe 路径（可省略，按 PATH 查找）"}
  auto：先直接启动，若很快退出再转区重试。
"""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


def find_locale_emulator(configured=None):
    for candidate in (configured, os.environ.get('GLK_LOCALE_EMULATOR'), shutil.which('LEProc.exe'), shutil.which('LEProc')):
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def game_pids(exe):
    """按可执行文件完整路径查找进程（不区分大小写）。"""
    target = str(Path(exe).resolve()).lower()
    script = ('[Console]::OutputEncoding = [Text.Encoding]::UTF8; Get-CimInstance Win32_Process | Where-Object ExecutablePath | '
              'Select-Object ProcessId,ExecutablePath | ConvertTo-Json -Compress')
    out = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True, timeout=60).stdout
    rows = json.loads(out.decode('utf-8', 'replace') or '[]')
    rows = [rows] if isinstance(rows, dict) else rows
    return {r['ProcessId'] for r in rows if str(r['ExecutablePath']).lower() == target}


def _japanese_profile(emulator):
    """从 LEProc 同目录的 LEConfig.xml 取非管理员的 ja-JP 全局配置 GUID。
    不用 -run：它读的是单程序配置，没有时会弹出 LEGUI 而不启动游戏。"""
    import xml.etree.ElementTree as ET
    config = Path(emulator).with_name('LEConfig.xml')
    if not config.is_file():
        return None
    for profile in ET.parse(config).getroot().iter('Profile'):
        if profile.findtext('Location') == 'ja-JP' and profile.findtext('RunAsAdmin') != 'true':
            return profile.get('Guid')
    return None


class Session:
    def __init__(self, exe, locale_emulator=None):
        self.exe = Path(exe).resolve()
        self.locale = bool(locale_emulator)
        if locale_emulator:
            guid = _japanese_profile(locale_emulator)
            if not guid:
                raise RuntimeError('Locale Emulator 没有日语（ja-JP）配置；请先在 LEGUI 里建一个')
            args = [str(locale_emulator), '-runas', guid, str(self.exe)]
        else:
            args = [str(self.exe)]
        self.child = subprocess.Popen(args, cwd=self.exe.parent)

    def pids(self):
        return game_pids(self.exe)

    def alive(self):
        return bool(self.pids())

    def stop(self):
        for pid in self.pids() | {self.child.pid}:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)


def system_is_japanese():
    import ctypes
    return ctypes.windll.kernel32.GetACP() == 932


def start(exe, options=None, settle=8, legacy_codepage=False):
    """按配置启动，返回 (Session 或 None, 说明 dict)。
    auto：legacy_codepage（引擎按系统代码页读日文，如吉里吉里）且系统非日文时直接转区；
    否则先直接启动，settle 秒内退出再转区重试。"""
    options = options or {}
    mode = options.get('locale', 'auto')
    emulator = find_locale_emulator(options.get('locale_emulator'))
    if mode == 'auto' and legacy_codepage and not system_is_japanese():
        if not emulator:
            return None, {'error': '该引擎在非日文系统直接启动会乱码，需要转区；找不到 LEProc.exe（glk.json 的 launch.locale_emulator）'}
        mode = 'ja'
    if mode == 'ja':
        if not emulator:
            return None, {'error': '配置要求转区启动，但找不到 LEProc.exe；请在 glk.json 的 launch.locale_emulator 填写路径'}
        return Session(exe, emulator), {'locale_emulator': True}
    session = Session(exe)
    if mode == 'none':
        return session, {'locale_emulator': False}
    deadline = time.time() + settle
    while time.time() < deadline:
        time.sleep(1)
        if session.child.poll() is not None and not session.alive():
            break
    else:
        return session, {'locale_emulator': False}
    if not emulator:
        return None, {'error': f'直接启动 {settle} 秒内退出；可能需要转区，但找不到 LEProc.exe（launch.locale_emulator）'}
    return Session(exe, emulator), {'locale_emulator': True, 'note': '直接启动很快退出，已改用转区启动'}


def probe_alive(exe, options=None, seconds=15, legacy_codepage=False):
    """启动若干秒后检查游戏进程仍在；结束后关闭进程。供无法读取画面的引擎做基本检查。"""
    session, info = start(exe, options, legacy_codepage=legacy_codepage)
    if session is None:
        return {'ok': False, **info}
    try:
        time.sleep(seconds)
        alive = session.alive()
    finally:
        session.stop()
    return {'ok': alive, **info, 'note': f'启动 {seconds} 秒内{"未" if alive else "已"}退出；画面文字需截图确认'}
