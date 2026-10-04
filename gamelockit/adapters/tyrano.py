"""TyranoScript 适配器（Electron app.asar / NW.js package.nw / 散文件 data/）。

直接替换 .ks 剧本中的正文行、#说话人行，以及纯标签行里的 text= / jname= 属性。
[iscript]…[endscript] 与 [html]…[endhtml] 内的代码不触碰；标签原样作为保护标记。
"""
from pathlib import Path
import io
import json
import zipfile

from . import register
from .base import Adapter, Occurrence, copy_tree
from .. import launch, saveguard
from ..formats import asar
from ..formats.kag import TAG, apply_units, scenario_units
from ..textutil import is_candidate

@register
class TyranoAdapter(Adapter):
    name = 'tyrano'
    title = 'TyranoScript（Electron / NW.js）'
    display_layer = False
    token_patterns = (r'\[[^\]\n]*\]',)
    translator_notes = ('- 方括号标签（如 [r] [l] [p] [ruby text=…] [emb exp=…]）原样保留，可按中文语序移动但不得增删或修改。\n'
                        '- 条目以 #speaker 开头的上下文表示说话人名字，只翻译名字本身。')

    @classmethod
    def detect(cls, game_dir):
        game_dir = Path(game_dir)
        for rel in ('resources/app.asar', 'package.nw', 'www/package.nw'):
            p = game_dir / rel
            if p.is_file():
                try:
                    names = cls._names(p)
                except (ValueError, OSError, zipfile.BadZipFile):
                    continue
                if any(n.startswith('data/scenario/') and n.endswith('.ks') for n in names):
                    return 90
        return 85 if (game_dir / 'data' / 'scenario').is_dir() and (game_dir / 'tyrano').is_dir() else 0

    @staticmethod
    def _names(path):
        if path.suffix == '.asar':
            return asar.read(path.read_bytes()).keys()
        with zipfile.ZipFile(path) as z:
            return z.namelist()

    def container(self):
        for rel in ('resources/app.asar', 'package.nw', 'www/package.nw'):
            if (self.game / rel).is_file():
                return rel
        return None

    def sources(self, root=None):
        root = Path(root) if root else self.game
        rel = self.container()
        if rel and rel.endswith('.asar'):
            path = root / rel
            return asar.read(path.read_bytes(), path.with_name(path.name + '.unpacked'))
        if rel:
            with zipfile.ZipFile(root / rel) as z:
                return {n: z.read(n) for n in z.namelist() if not n.endswith('/')}
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / 'data').rglob('*.ks')}

    @staticmethod
    def scenario(files):
        return {k: v for k, v in files.items() if k.startswith('data/') and k.endswith('.ks')}

    def extract(self):
        lang = self.ws.source_lang
        for rel, raw in sorted(self.scenario(self.sources()).items()):
            text = raw.decode('utf-8-sig', errors='replace')
            for n, kind, _, _, source in scenario_units(text):
                if is_candidate(TAG.sub('', source), lang):
                    hint = 'unknown' if kind == 'speaker' else 'display'
                    yield Occurrence(source, 'scenario', f'{rel}:{n + 1}', kind, hint)

    def build(self, mapping, out_dir):
        out_dir = Path(out_dir)
        copy_tree(self.game, out_dir, exclude=self.personal_data_globs)
        files = self.scenario(self.sources())
        replacements, count = {}, 0
        for rel, raw in files.items():
            bom = raw.startswith(b'\xef\xbb\xbf')
            text = raw.decode('utf-8-sig', errors='strict')
            new, n = apply_units(text, mapping)
            if n:
                replacements[rel] = (b'\xef\xbb\xbf' if bom else b'') + new.encode('utf-8')
                count += n
        rel = self.container()
        if rel and rel.endswith('.asar'):
            target = out_dir / rel
            target.write_bytes(asar.rewrite((self.game / rel).read_bytes(), replacements))
        elif rel:
            src, target = self.game / rel, out_dir / rel
            buffer = io.BytesIO()
            with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zout:
                for info in zin.infolist():
                    zout.writestr(info, replacements.get(info.filename, zin.read(info.filename)))
            target.write_bytes(buffer.getvalue())
        else:
            for path, content in replacements.items():
                (out_dir / path).write_bytes(content)
        return {'files': len(replacements), 'replacements': count, 'container': rel or 'data/'}

    def shared_save_locations(self, out_dir):
        """Electron / NW.js 的 localStorage 存档在 AppData 下以应用名命名的目录，汉化副本与原版共用。"""
        rel = self.container()
        if not rel:
            return []
        files = self.sources(out_dir)
        meta = json.loads(files.get('package.json', b'{}').decode('utf-8-sig'))
        names = {n for n in (meta.get('productName'), meta.get('name')) if isinstance(n, str) and n.strip()}
        if not names:
            raise RuntimeError('package.json 缺少应用名，无法定位共用存档，拒绝自动启动')
        found = []
        for n in sorted(names):
            found += [('dir', saveguard.appdata(n)), ('dir', saveguard.appdata(n, local=True))]
        return found

    def launcher(self, out_dir):
        exes = [p for p in Path(out_dir).glob('*.exe') if 'unins' not in p.name.lower()]
        return exes[0].name if exes else None

    def probe(self, out_dir, seconds=15):
        exe = self.launcher(out_dir)
        if not exe:
            return {'skipped': '找不到 EXE'}
        return launch.probe_alive(Path(out_dir) / exe, self.ws.config.get('launch'), seconds, self.legacy_codepage)
