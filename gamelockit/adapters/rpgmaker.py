"""RPG Maker MV / MZ 适配器：直接替换 data/*.json 中的显示字段（不改脚本与插件代码）。

只替换结构上确定用于显示的字段；数据库名称等若在脚本、插件代码或插件参数中出现过同样文字，
则标为待审（可能被脚本按名字查找）。直接替换会改变运行时字符串，因此 dual 用途不放行。
"""
import json
from pathlib import Path
import re

from . import register
from .base import Adapter, Occurrence, copy_tree
from .. import launch
from ..textutil import is_candidate

DB_FIELDS = {
    'Actors.json': ('name', 'nickname', 'profile'),
    'Classes.json': ('name',),
    'Skills.json': ('name', 'description', 'message1', 'message2'),
    'Items.json': ('name', 'description'),
    'Weapons.json': ('name', 'description'),
    'Armors.json': ('name', 'description'),
    'Enemies.json': ('name',),
    'States.json': ('name', 'message1', 'message2', 'message3', 'message4'),
    'Troops.json': (),
}
SYSTEM_LISTS = ('elements', 'skillTypes', 'weaponTypes', 'armorTypes', 'equipTypes')
# 事件指令：code → 显示文字所在参数下标
TEXT_COMMANDS = {401: (0,), 405: (0,), 320: (1,), 324: (1,), 325: (1,)}
SCRIPT_COMMANDS = (355, 655, 122, 111, 356)
TOKEN = r'\\[A-Za-z]+\[[^\]\n]*\]|\\[A-Za-z]+<[^>\n]*>|\\[A-Za-z]+|\\[{}$.|!><^\\]'


def _data_dir(game):
    for rel in ('www/data', 'data'):
        if (game / rel / 'System.json').is_file():
            return game / rel
    return None


@register
class RpgMakerAdapter(Adapter):
    name = 'rpgmaker'
    title = 'RPG Maker MV / MZ'
    display_layer = False
    token_patterns = (TOKEN,)
    personal_data_globs = ('save/*', 'www/save/*', '*.rpgsave', '*.rmmzsave')
    translator_notes = ('- 反斜杠控制符原样保留：\\C[n] \\I[n] \\N[n] \\V[n] \\P[n] \\G \\{ \\} \\. \\| \\! \\> \\< \\^ 以及插件扩展的 \\XX[...] / \\XX<...>。\n'
                        '- 对话框每行（一条 401）宽度有限：每行译文尽量不超过约 24 个汉字，不要把多行合并成一行，也不要增加行数。')

    @classmethod
    def detect(cls, game_dir):
        game_dir = Path(game_dir)
        data = _data_dir(game_dir)
        if data is None:
            return 0
        js = data.parent / 'js'
        return 90 if (js / 'rpg_core.js').exists() or (js / 'rmmz_core.js').exists() else 60

    def data_dir(self, root=None):
        found = _data_dir(Path(root) if root else self.game)
        if found is None:
            raise FileNotFoundError('找不到 data/System.json（游戏可能被打包进 EXE，需要先解包）')
        return found

    def script_corpus(self):
        """脚本、插件代码与插件参数文本，用于判断数据库名称是否被代码引用。"""
        data = self.data_dir()
        parts = []
        js = data.parent / 'js'
        if js.exists():
            for path in js.rglob('*.js'):
                if path.name not in ('rpg_core.js', 'rpg_managers.js', 'rpg_objects.js', 'rpg_scenes.js', 'rpg_sprites.js', 'rpg_windows.js') and not path.name.startswith('rmmz_'):
                    parts.append(path.read_text(encoding='utf-8', errors='replace'))
        for path in data.glob('*.json'):
            for _, cmd in self._commands(self._load(path)):
                if cmd.get('code') in SCRIPT_COMMANDS:
                    parts.append(json.dumps(cmd.get('parameters'), ensure_ascii=False))
        return '\n'.join(parts)

    @staticmethod
    def _load(path):
        return json.loads(path.read_text(encoding='utf-8-sig'))

    @staticmethod
    def _commands(value, path=''):
        """遍历任意 JSON 中的事件指令列表（地图、公共事件、敌群均适用）。"""
        if isinstance(value, dict):
            if 'code' in value and 'parameters' in value and isinstance(value.get('parameters'), list):
                yield path, value
            for k, v in value.items():
                yield from RpgMakerAdapter._commands(v, f'{path}/{k}')
        elif isinstance(value, list):
            for i, v in enumerate(value):
                yield from RpgMakerAdapter._commands(v, f'{path}/{i}')

    def walk(self, data_dir):
        """产出 (文件名, JSON 路径元组, 原文, 上下文, 结构判断)。build 与 extract 共用，保证位置一致。"""
        for path in sorted(data_dir.glob('*.json')):
            name = path.name
            value = self._load(path)
            if name in DB_FIELDS:
                for i, row in enumerate(value):
                    if isinstance(row, dict):
                        for field in DB_FIELDS[name]:
                            if isinstance(row.get(field), str):
                                yield name, (i, field), row[field], field, 'name' if field == 'name' or field == 'nickname' else 'text'
            elif name == 'System.json':
                for key in ('gameTitle', 'currencyUnit'):
                    if isinstance(value.get(key), str):
                        yield name, (key,), value[key], key, 'name'
                for key in SYSTEM_LISTS:
                    for i, text in enumerate(value.get(key) or []):
                        if isinstance(text, str):
                            yield name, (key, i), text, key, 'name'
                terms = value.get('terms') or {}
                for group in ('basic', 'commands', 'params'):
                    for i, text in enumerate(terms.get(group) or []):
                        if isinstance(text, str):
                            yield name, ('terms', group, i), text, f'terms.{group}', 'name'
                for key, text in (terms.get('messages') or {}).items():
                    if isinstance(text, str):
                        yield name, ('terms', 'messages', key), text, f'terms.messages.{key}', 'text'
            elif re.fullmatch(r'Map\d+\.json', name) and isinstance(value, dict) and isinstance(value.get('displayName'), str):
                yield name, ('displayName',), value['displayName'], 'displayName', 'name'
            for jpath, cmd in self._commands(value):
                code, params = cmd.get('code'), cmd['parameters']
                keys = tuple(int(k) if k.isdigit() else k for k in jpath.strip('/').split('/')) if jpath else ()
                if code in TEXT_COMMANDS:
                    for idx in TEXT_COMMANDS[code]:
                        if idx < len(params) and isinstance(params[idx], str):
                            yield name, keys + ('parameters', idx), params[idx], f'event:{code}', 'text'
                elif code == 101 and len(params) > 4 and isinstance(params[4], str):
                    yield name, keys + ('parameters', 4), params[4], 'event:101:speaker', 'name'
                elif code == 102 and params and isinstance(params[0], list):
                    for i, text in enumerate(params[0]):
                        if isinstance(text, str):
                            yield name, keys + ('parameters', 0, i), text, 'event:102:choice', 'text'
                elif code == 402 and len(params) > 1 and isinstance(params[1], str):
                    yield name, keys + ('parameters', 1), params[1], 'event:402:choice-branch', 'text'

    def extract(self):
        lang = self.ws.source_lang
        corpus = self.script_corpus()
        for name, keys, text, context, kind in self.walk(self.data_dir()):
            if not is_candidate(text, lang):
                continue
            # 名称类在代码中出现过 → 可能被按名查找，交给人工审核。
            hint = 'unknown' if kind == 'name' and text.strip() and text.strip() in corpus else 'display'
            yield Occurrence(text, 'json', f'{name}#{"/".join(map(str, keys))}', context, hint)
        for path in sorted((self.data_dir().parent / 'js').glob('plugins.js')):
            body = path.read_text(encoding='utf-8', errors='replace')
            for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', body):
                try:
                    text = json.loads(f'"{m.group(1)}"')
                except ValueError:
                    continue
                if is_candidate(text, lang) and len(text) < 200 and not text.lstrip().startswith(('{', '[')):
                    yield Occurrence(text, 'plugin-param', f'js/plugins.js@{m.start()}', '', 'protected')

    def build(self, mapping, out_dir):
        out_dir = Path(out_dir)
        copy_tree(self.game, out_dir, exclude=self.personal_data_globs)
        data_dir = self.data_dir(out_dir)
        edits = {}
        for name, keys, text, _, _ in self.walk(self.data_dir()):
            if text in mapping and mapping[text] != text:
                edits.setdefault(name, []).append((keys, mapping[text]))
        changed = 0
        for name, items in edits.items():
            path = data_dir / name
            raw = path.read_text(encoding='utf-8-sig')
            value = json.loads(raw)
            for keys, target in items:
                node = value
                for k in keys[:-1]:
                    node = node[k]
                node[keys[-1]] = target
                changed += 1
            path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
            json.loads(path.read_text(encoding='utf-8'))
        overrides = self.ws.path('overrides')
        replaced = []
        if overrides.exists():
            for src in sorted(p for p in overrides.rglob('*') if p.is_file()):
                rel = src.relative_to(overrides)
                if not (out_dir / rel).exists():
                    raise ValueError(f'覆盖文件在游戏中不存在: {rel.as_posix()}')
                (out_dir / rel).write_bytes(src.read_bytes())
                replaced.append(rel.as_posix())
        return {'files': len(edits), 'replacements': changed, 'overrides': replaced}

    def launcher(self, out_dir):
        exes = [p for p in Path(out_dir).glob('*.exe') if p.name.lower() not in ('notification_helper.exe',)]
        return exes[0].name if exes else None

    def probe(self, out_dir, seconds=15):
        exe = self.launcher(out_dir)
        if not exe:
            return {'skipped': '找不到 EXE'}
        return launch.probe_alive(Path(out_dir) / exe, self.ws.config.get('launch'), seconds, self.legacy_codepage)
