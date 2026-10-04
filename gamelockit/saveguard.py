"""启动汉化副本前后保护“与原版共用”的存档位置（注册表 / AppData）。

有些引擎把存档写在游戏目录之外（Unity PlayerPrefs、Electron/NW.js localStorage），
汉化副本与原版共用同一位置。自动启动检查/截图前先备份，结束后原样还原，
确保测试不会改动玩家原有进度。
"""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import subprocess
import time

from .integrity import sha256


def _dir_digest(path):
    path = Path(path)
    if not path.exists():
        return None
    return {p.relative_to(path).as_posix(): sha256(p) for p in sorted(path.rglob('*')) if p.is_file()}


def _reg(*args):
    return subprocess.run(['reg', *args], capture_output=True, text=True, encoding='mbcs', errors='replace')


def _reg_dump(key):
    done = _reg('query', key, '/s')
    return done.stdout if done.returncode == 0 else None


def appdata(*parts, local=False):
    base = os.environ.get('LOCALAPPDATA' if local else 'APPDATA')
    return Path(base, *parts) if base else None


def locallow(*parts):
    return Path(os.environ.get('USERPROFILE', '~'), 'AppData', 'LocalLow', *parts).expanduser()


def _restore_dir(where, before, copy, wait=30):
    """逐文件还原（不整目录删除）；游戏刚退出时文件可能仍被占用，占用期间重试。"""
    deadline = time.time() + wait
    while True:
        try:
            now = _dir_digest(where)
            if now == before:
                return True
            for rel in set(now or ()) - set(before or ()):
                (where / rel).unlink()
            for rel, digest in (before or {}).items():
                if (now or {}).get(rel) != digest:
                    (where / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(copy / rel, where / rel)
            if before is None:
                for d in sorted((p for p in where.rglob('*') if p.is_dir()), reverse=True):
                    d.rmdir()
                where.rmdir()
        except PermissionError:
            if time.time() > deadline:
                return False
            time.sleep(1)


@contextmanager
def guard(locations, backup_root):
    """locations: [('dir', Path) | ('reg', 'HKCU\\Software\\…')]。退出时还原并核对，失败抛 RuntimeError。"""
    backup_root = Path(backup_root) / time.strftime('%Y%m%d-%H%M%S')
    saved = []
    for i, (kind, where) in enumerate(locations):
        if kind == 'dir':
            before = _dir_digest(where)
            copy = backup_root / f'dir{i}'
            if before is not None:
                shutil.copytree(where, copy)
            saved.append((kind, Path(where), before, copy))
        elif kind == 'reg':
            before = _reg_dump(where)
            copy = backup_root / f'reg{i}.reg'
            if before is not None:
                backup_root.mkdir(parents=True, exist_ok=True)
                if _reg('export', where, str(copy), '/y').returncode != 0:
                    raise RuntimeError(f'无法备份注册表 {where}，拒绝启动')
            saved.append((kind, where, before, copy))
        else:
            raise ValueError(kind)
    try:
        yield [str(s[1]) for s in saved]
    finally:
        problems = []
        for kind, where, before, copy in saved:
            if kind == 'dir':
                if not _restore_dir(where, before, copy):
                    problems.append(f'目录未能还原: {where}（备份在 {copy}）')
            else:
                if _reg_dump(where) == before:
                    continue
                _reg('delete', where, '/f')
                if before is not None:
                    _reg('import', str(copy))
                if _reg_dump(where) != before:
                    problems.append(f'注册表未能还原: {where}（备份在 {copy}）')
        if problems:
            raise RuntimeError('；'.join(problems))
