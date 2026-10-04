"""吉里吉里 2 / KAG3 / 吉里吉里Z 适配器（未加密的 XP3 或散文件）。

提取 .ks 剧本正文与纯标签行的 text= 属性，以及 .tjs 中的字符串字面量（后者一律待审：
可能是菜单/对话框文字，也可能参与判断或是调试信息）。
注入方式：原版 data.xp3 不动，把改过的脚本以 UTF-16LE(BOM) 写进新的补丁归档 patch.xp3
（已存在则用 patchN.xp3），KAG3 的 Initialize.tjs 会自动挂载并优先读取补丁中的同名文件。
直接替换会改变运行时字符串，因此 dual 用途不放行。
"""
from pathlib import Path, PurePosixPath
import re

from . import register
from .base import Adapter, Occurrence, copy_tree
from .. import launch
from ..formats import kag, tjs, xp3
from ..textutil import is_candidate

SCRIPT_EXT = ('.ks', '.tjs')
# 挂载补丁前就执行的脚本，补丁无法覆盖
EARLY_SCRIPTS = ('startup.tjs', 'initialize.tjs')
SKIP_EXE = ('mtool', 'unins', 'notification', 'krkrrel', 'krconfig', 'nw.exe', 'payload')
SPEAKER = re.compile(r'【[^】\n]+】')


def decode(raw):
    if raw[:2] == b'\xff\xfe':
        return raw[2:].decode('utf-16le')
    if raw[:3] == b'\xef\xbb\xbf':
        return raw[3:].decode('utf-8')
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return raw.decode('cp932')


def encode(text):
    # 吉里吉里 2/Z 都识别带 BOM 的 UTF-16LE，且不依赖系统区域代码页
    return b'\xff\xfe' + text.encode('utf-16le')


def _patch_order(path):
    m = re.fullmatch(r'patch(\d*)\.xp3', path.name.lower())
    if not m:
        return (0, path.name.lower() != 'data.xp3', path.name.lower())
    return (1, int(m.group(1) or 1), '')


@register
class KirikiriAdapter(Adapter):
    name = 'kirikiri'
    title = '吉里吉里 2 / KAG3 / 吉里吉里Z（未加密 XP3）'
    display_layer = False
    legacy_codepage = True
    token_patterns = (r'\[[^\]\n]*\]', tjs.ESCAPE)
    personal_data_globs = ('savedata/*', '*.log', '*.cf', '*.cfu')
    translator_notes = ('- 方括号标签（[r] [l] [p] [np] [emb exp=…] [ruby text=…] 等）原样保留，可按中文语序移动但不得增删或修改。\n'
                        '- 上下文为 tjs-literal 的条目是脚本字符串：反斜杠转义（\\n \\" 等）原样保留，不得加入未转义的引号。\n'
                        '- 形如【名字】的整行是说话人名，只译名字本身并保留【】。')

    @classmethod
    def detect(cls, game_dir):
        game_dir = Path(game_dir)
        for arc in game_dir.glob('*.xp3'):
            try:
                names = [e.name.lower() for e in xp3.entries(arc)]
            except (ValueError, OSError):
                continue
            if any(n.endswith('startup.tjs') or n.endswith('.ks') for n in names):
                return 90
        return 70 if (game_dir / 'data' / 'startup.tjs').is_file() else 0

    def archives(self, root=None):
        root = Path(root) if root else self.game
        return sorted((p for p in root.glob('*.xp3')), key=_patch_order)

    def scripts(self):
        """合并后的脚本 {键: (归档或目录, 条目名, 文本)}；后挂载的补丁按同名覆盖。"""
        merged, owner = {}, {}
        loose = self.game / 'data'
        if loose.is_dir():
            for path in sorted(loose.rglob('*')):
                if path.suffix.lower() in SCRIPT_EXT:
                    name = path.relative_to(loose).as_posix()
                    merged[self._key(name)] = ('data/', name, path.read_bytes())
        for arc in self.archives():
            files = xp3.read(arc, lambda n: n.lower().endswith(SCRIPT_EXT))
            for name, raw in files.items():
                key = self._key(name)
                if arc.name.lower() == 'data.xp3' and key in owner and owner[key] != name:
                    raise ValueError(f'data.xp3 内有同名脚本 {key}，补丁按文件名覆盖会冲突，需手动处理')
                owner.setdefault(key, name)
                merged[key] = (arc.name, name, raw)
        return {k: (src, name, decode(raw)) for k, (src, name, raw) in merged.items()}

    @staticmethod
    def _key(name):
        return PurePosixPath(name).name.lower()

    def extract(self):
        lang = self.ws.source_lang
        items = sorted(self.scripts().items())
        # 先登记 tjs 字面量：同一文字若也出现在剧本里，用途不会被剧本的“显示”预判直接放行
        for key, (src, name, text) in items:
            if not key.endswith('.tjs'):
                continue
            hint = 'protected' if key in EARLY_SCRIPTS else 'unknown'
            for start, _, _, content in tjs.string_literals(text):
                if is_candidate(content, lang):
                    yield Occurrence(content, 'tjs-literal', f'{src}>{name}@{start}', 'tjs-literal', hint)
        for key, (src, name, text) in items:
            if not key.endswith('.ks'):
                continue
            for n, kind, _, _, source in kag.scenario_units(text):
                visible = kag.TAG.sub('', source).strip()
                if not is_candidate(visible, lang):
                    continue
                context = 'speaker' if SPEAKER.fullmatch(visible) else kind
                hint = 'display' if kind == 'text' else 'unknown'
                yield Occurrence(source, 'scenario', f'{src}>{name}:{n + 1}', context, hint)

    def build(self, mapping, out_dir):
        out_dir = Path(out_dir)
        copy_tree(self.game, out_dir, exclude=self.personal_data_globs)
        patched, count = {}, 0
        for key, (_, name, text) in self.scripts().items():
            if key in EARLY_SCRIPTS:
                continue
            if key.endswith('.ks'):
                new, n = kag.apply_units(text, mapping)
            else:
                new, n = tjs.apply_literals(text, mapping)
            if n:
                patched[PurePosixPath(name).name] = encode(new)
                count += n
        target = self.patch_name(out_dir)
        if patched:
            xp3.write(out_dir / target, patched)
            check = xp3.read(out_dir / target)
            if check != patched:
                raise ValueError('补丁归档回读不一致')
        return {'patch': target if patched else None, 'files': len(patched), 'replacements': count}

    def patch_name(self, root):
        names = {p.name.lower() for p in Path(root).glob('*.xp3')}
        if 'patch.xp3' not in names:
            return 'patch.xp3'
        n = 2
        while f'patch{n}.xp3' in names:
            n += 1
        return f'patch{n}.xp3'

    def launcher(self, out_dir):
        exes = [p for p in sorted(Path(out_dir).glob('*.[eE][xX][eE]'))
                if not any(s in p.name.lower() for s in SKIP_EXE)]
        configured = self.options.get('launcher')
        if configured and (Path(out_dir) / configured).is_file():
            return configured
        return exes[0].name if exes else None

    def probe(self, out_dir, seconds=15):
        exe = self.launcher(out_dir)
        if not exe:
            return {'skipped': '找不到 EXE'}
        return launch.probe_alive(Path(out_dir) / exe, self.ws.config.get('launch'), seconds, self.legacy_codepage)
