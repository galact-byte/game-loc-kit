"""汉化工作区：一个游戏一个目录，存放配置、目录库、解包文件、审核与质检记录。

工作区包含游戏原文与译文，必须放在仓库之外，且不得公开。
"""
import json
import os
import tempfile
from pathlib import Path

CONFIG_NAME = 'glk.json'

DEFAULT_CONFIG = {
    'source_lang': 'ja',
    'target_lang': 'zh-Hans',
    'translator': {
        # 子 Agent 命令模板；{prompt} 与 {worker} 会被替换。默认使用 pi 的无会话打印模式。
        'command': ['pi', '--no-session', '--no-skills', '--no-context-files', '--tools', 'read,bash,write', '--mode', 'json', '--print', '{prompt}'],
        'slots': 5,
        'max_concurrency': 2,
        'batch': 300,
        'transient_markers': ['rate_limit', 'rate limit', 'too many requests', 'concurrency_limit', 'upstream_error', 'overloaded', 'service unavailable'],
    },
    'adapter': {},
    # 汉化副本启动方式（auto/ja/none）；见 gamelockit/launch.py。auto 会按引擎是否依赖系统代码页及启动是否秒退决定转区。
    'launch': {'locale': 'auto', 'locale_emulator': None},
}


def write_json(path, value):
    """原子写入，避免中断留下半个文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.tmp-', suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def merge(base, override):
    result = dict(base)
    for key, value in override.items():
        result[key] = merge(base[key], value) if isinstance(value, dict) and isinstance(base.get(key), dict) else value
    return result


class Workspace:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config_path = self.root / CONFIG_NAME
        if not self.config_path.exists():
            raise FileNotFoundError(f'不是 game-loc-kit 工作区（缺少 {CONFIG_NAME}）: {self.root}')
        self.config = merge(DEFAULT_CONFIG, read_json(self.config_path))
        self.game_dir = Path(self.config['game_dir'])
        self.engine = self.config['engine']

    @classmethod
    def create(cls, root, game_dir, engine, **extra):
        root = Path(root).resolve()
        game_dir = Path(game_dir).resolve()
        if root == game_dir or game_dir in root.parents:
            raise ValueError('工作区不能放在游戏目录内，避免污染原版文件')
        if (root / CONFIG_NAME).exists():
            raise FileExistsError(f'工作区已存在: {root}')
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / CONFIG_NAME, merge({'game_dir': str(game_dir), 'engine': engine}, extra))
        return cls(root)

    def save(self):
        write_json(self.config_path, self.config)

    def path(self, *parts):
        return self.root.joinpath(*parts)

    @property
    def db(self):
        return self.path('catalog.sqlite3')

    @property
    def unpacked(self):
        return self.path('unpacked')

    @property
    def stop_file(self):
        return self.path('STOP')

    @property
    def source_lang(self):
        return self.config['source_lang']
