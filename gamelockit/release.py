"""发布：生成可直接分发的 原版/ 与 汉化版/ 目录，附校验值与无剧透使用说明。"""
from datetime import date
from pathlib import Path
import shutil

from .adapters.base import copy_tree
from .integrity import sha256

TEMPLATE = Path(__file__).with_name('templates') / 'usage_zh.txt'


def make_release(ws, adapter, build_dir, out_dir, title=None, include_original=True):
    build_dir, out_dir = Path(build_dir), Path(out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f'发布目录非空，拒绝覆盖: {out_dir}')
    zh = out_dir / '汉化版'
    copy_tree(build_dir, zh, exclude=adapter.personal_data_globs)
    if include_original:
        copy_tree(ws.game_dir, out_dir / '原版', exclude=adapter.personal_data_globs)
    launcher = adapter.launcher(zh) or '（见游戏目录中的可执行文件）'
    exes = sorted(p for p in zh.rglob('*.exe'))
    (zh / 'SHA256.txt').write_text(''.join(f'{sha256(p)}  {p.relative_to(zh).as_posix()}\n' for p in exes), encoding='utf-8')
    text = TEMPLATE.read_text(encoding='utf-8').format(launcher=launcher, title=title or ws.game_dir.name, date=date.today().isoformat())
    (zh / '使用说明.txt').write_text(text, encoding='utf-8')
    return {'out_dir': str(out_dir), 'executables': [p.relative_to(zh).as_posix() for p in exes]}


def remove_tree(path):
    shutil.rmtree(path)
