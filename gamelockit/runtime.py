"""源码与 Windows 独立程序共用的 CLI 启动命令。"""
from pathlib import Path
import sys


def cli_command(*args):
    executable = Path(sys.executable)
    if getattr(sys, 'frozen', False):
        executable = executable.with_name('glk.exe')
        if not executable.is_file():
            raise FileNotFoundError(f'缺少 {executable}，请重新完整解压 Windows 包。')
        return [str(executable), *args]
    if executable.stem.lower() == 'pythonw':
        executable = executable.with_name('python.exe')
    return [str(executable), '-m', 'gamelockit', *args]
