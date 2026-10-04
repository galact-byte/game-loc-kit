"""适配器注册与引擎识别。"""
from pathlib import Path

from .base import Adapter, Occurrence  # noqa: F401

_REGISTRY = {}


def register(cls):
    _REGISTRY[cls.name] = cls
    return cls


MODULES = ('godot4', 'rpgmaker', 'unity', 'kirikiri', 'tyrano', 'wolf')


def _load():
    # 可选依赖（pycryptodome / UnityPy）缺失时只跳过对应引擎，不影响其他引擎。
    import importlib
    for name in MODULES:
        try:
            importlib.import_module(f'{__name__}.{name}')
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith(__package__.split('.')[0]):
                raise
            _MISSING[name] = exc.name


_MISSING = {}


def adapters():
    _load()
    return dict(_REGISTRY)


def get(name):
    found = adapters().get(name)
    if found is None and name in _MISSING:
        raise KeyError(f'引擎适配器 {name} 缺少依赖 {_MISSING[name]}，请先 pip install')
    if found is None:
        raise KeyError(f'未知引擎适配器: {name}（可用: {", ".join(sorted(_REGISTRY))}）')
    return found


def detect(game_dir):
    game_dir = Path(game_dir)
    scores = []
    for cls in adapters().values():
        try:
            score = cls.detect(game_dir)
        except OSError:
            score = 0
        if score:
            scores.append((score, cls.name))
    return sorted(scores, reverse=True)
