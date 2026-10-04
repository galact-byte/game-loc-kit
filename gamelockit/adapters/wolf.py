"""WOLF RPG エディター 2.x / 3.x 适配器。

文字所在：BasicData 下的 CommonEvent.dat、DataBase/CDataBase/SysDatabase（.project + .dat）、
Game.dat，以及 MapData/*.mps。数据若封在加密的 .wolf 归档中，unpack 用 UberWolfCli 解到工作区
（不动原版）；构建时副本里去掉这些归档，改放解开并替换过的散文件，引擎会读取散文件。
直接替换会改变运行时字符串，因此 dual 用途不放行；字符串比较/数据库操作的参数一律保护。
"""
import os
from pathlib import Path
import shutil
import subprocess

from . import register
from .base import Adapter, Occurrence, copy_tree
from .. import launch
from ..formats import wolf
from ..textutil import is_candidate

DATA_ARCHIVES = ('BasicData.wolf', 'MapData.wolf', 'Data.wolf')
DATABASES = ('DataBase', 'CDataBase', 'SysDatabase')
# 解析器给出的结构类别 → 用途预判；同一文字的第一个出处决定预判，所以按保护→待审→显示的顺序产出
KIND_HINT = {'logic': 'protected', 'title': 'protected', 'font': None,
             'set-string': 'unknown', 'other': 'unknown', 'db': 'unknown', 'version': 'unknown',
             'message': 'display', 'choice': 'display', 'picture-text': 'display'}
HINT_ORDER = {'protected': 0, 'unknown': 1, 'display': 2}
SKIP_EXE = ('mtool', 'unins', 'config', 'editor', 'uberwolf')


@register
class WolfAdapter(Adapter):
    name = 'wolf'
    title = 'WOLF RPG エディター 2.x / 3.x'
    display_layer = False
    token_patterns = (r'\\[A-Za-z]+\[[^\]\n]*\]', r'\\[A-Za-z]+[+-]?', r'\\[!.^|<>-]', r'<[CLR]>')
    personal_data_globs = ('Save/*', 'save/*', '*.sav', '*.log')
    translator_notes = ('- 反斜杠控制符（\\c[2] \\f[24] \\A+ \\E \\N \\font[1] \\cdb[0:1:2] 等）与 <C> <R> 原样保留，不得增删或修改。\n'
                        '- 文中实际换行即游戏内换行；中文字宽较大，单行不要明显长于原文。')

    @classmethod
    def detect(cls, game_dir):
        data = Path(game_dir) / 'Data'
        if (data / 'BasicData' / 'CommonEvent.dat').is_file():
            return 90
        if any((data / n).is_file() for n in DATA_ARCHIVES) or (Path(game_dir) / 'Data.wolf').is_file():
            return 85
        return 0

    def __init__(self, ws):
        super().__init__(ws)
        self.source_encoding = self.options.get('source_encoding', 'cp932')

    # ---------- 解包 ----------
    def archived(self):
        """原版中需要解包的数据归档（相对游戏目录）。散文件已存在时以散文件为准，无需解包。"""
        data = self.game / 'Data'
        if (data / 'BasicData' / 'CommonEvent.dat').is_file():
            return []
        found = [p for p in (data / n for n in DATA_ARCHIVES) if p.is_file()]
        if (self.game / 'Data.wolf').is_file():
            found.append(self.game / 'Data.wolf')
        return [p.relative_to(self.game) for p in found]

    def data_root(self):
        """散的 Data 目录：原版自带的，或解包到工作区的。"""
        if not self.archived():
            return self.game / 'Data'
        return self.ws.unpacked / 'Data'

    def unpack(self):
        archives = self.archived()
        if not archives:
            return
        root = self.ws.unpacked
        if (root / 'Data' / 'BasicData' / 'CommonEvent.dat').is_file():
            return
        tool = self._uberwolf()
        root.mkdir(parents=True, exist_ok=True)
        exe = self.launcher(self.game)
        if exe:  # UberWolf 需要从游戏 EXE 中取解密参数
            shutil.copy2(self.game / exe, root / exe)
        for rel in archives:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.game / rel, root / rel)
        result = subprocess.run([tool, *[str(root / rel) for rel in archives]], capture_output=True,
                                text=True, errors='replace', timeout=1800)
        if result.returncode != 0 or not (root / 'Data' / 'BasicData' / 'CommonEvent.dat').is_file():
            raise RuntimeError(f'UberWolfCli 解包失败：{(result.stdout + result.stderr)[-300:]}')
        for rel in archives:
            (root / rel).unlink()

    def _uberwolf(self):
        configured = self.options.get('uberwolf') or os.environ.get('GLK_UBERWOLF')
        tool = configured or shutil.which('UberWolfCli') or shutil.which('UberWolfCli.exe')
        if not tool or not Path(tool).is_file():
            raise RuntimeError('数据封在加密的 .wolf 归档中，需要 UberWolfCli：在 工作区 glk.json 的 adapter.uberwolf '
                               '填写 UberWolfCli.exe 路径，或设置环境变量 GLK_UBERWOLF，或把它加入 PATH')
        return tool

    # ---------- 文件遍历 ----------
    def files(self, root=None):
        """[(相对 Data 的路径, 解析结果)]；解析结果含 spans、编码与回写所需信息。"""
        root = Path(root) if root else self.data_root()
        basic = root / 'BasicData'
        out = []
        ce = basic / 'CommonEvent.dat'
        data = ce.read_bytes()
        out.append(('BasicData/CommonEvent.dat', {'data': data, 'spans': wolf.parse_common_events(data),
                                                 'encoding': self._encoding(data, 'ce')}))
        for name in DATABASES:
            project, dat = basic / f'{name}.project', basic / f'{name}.dat'
            if not dat.is_file():
                continue
            data = dat.read_bytes()
            spans, _ = wolf.parse_database(project.read_bytes(), data, name)
            out.append((f'BasicData/{name}.dat', {'data': data, 'spans': spans, 'encoding': self._encoding(data, 'db')}))
        game = basic / 'Game.dat'
        if game.is_file():
            data = game.read_bytes()
            spans, size_at = wolf.parse_game_dat(data)
            out.append(('BasicData/Game.dat', {'data': data, 'spans': spans, 'size_at': size_at,
                                              'encoding': self._encoding(data, 'game')}))
        for mps in sorted((root / 'MapData').glob('*.mps')):
            data = mps.read_bytes()
            header, body, packed = wolf.map_body(data)
            out.append((f'MapData/{mps.name}', {'data': body, 'spans': wolf.parse_map(body), 'header': header,
                                               'packed': packed, 'encoding': self._encoding(data, 'map')}))
        return out

    def _encoding(self, data, kind):
        return wolf.encoding_of(data, kind) or self.source_encoding

    @staticmethod
    def texts(rel, info):
        """按文件编码解出全部字符串；有解不开的就整体报错，避免把乱码当原文提取或回写。"""
        enc, out, bad = info['encoding'], [], []
        for span in info['spans']:
            try:
                out.append(span.raw.decode(enc))
            except UnicodeDecodeError:
                out.append(None)
                bad.append(span.where)
        if bad:
            raise ValueError(f'{rel}: {len(bad)} 个字符串不是 {enc} 编码（如 {bad[0]}）。若数据并非日文原版，'
                             '请在 工作区 glk.json 的 adapter.source_encoding 指定实际编码（如 gbk）')
        return out

    def unicode(self):
        """是否为 UTF-8 数据（WOLF 3.x Unicode 版）；否则按系统代码页解读。"""
        return self.files()[0][1]['encoding'] == 'utf-8'

    @property
    def legacy_codepage(self):
        return self.source_encoding == 'cp932' and not self.unicode()

    # ---------- 提取 / 构建 ----------
    def extract(self):
        lang = self.ws.source_lang
        found = []
        for rel, info in self.files():
            texts = self.texts(rel, info)
            for i, span in enumerate(info['spans']):
                hint = KIND_HINT.get(span.kind)
                if hint is None:
                    continue
                text = texts[i]
                if is_candidate(text, lang):
                    found.append(Occurrence(text, f'wolf:{span.kind}', f'{rel}#{i}@{span.where}', span.kind, hint))
        found.sort(key=lambda o: HINT_ORDER[o.hint])
        yield from found

    def check_writable(self, encoding):
        if encoding in ('cp932', 'shift_jis', 'shift-jis', 'sjis'):
            raise ValueError('非 Unicode 版 WOLF（2.x）按日文代码页存字，写不进简体中文；整体转码又会波及'
                             '文件名等未解析字符串，暂不支持构建。可先用 WOLF 3.x 编辑器转为 Unicode 版再处理')

    def build(self, mapping, out_dir):
        out_dir = Path(out_dir)
        archived = {p.as_posix() for p in self.archived()}
        copy_tree(self.game, out_dir, exclude=(*self.personal_data_globs, *archived))
        if archived:  # 换成解开的散文件
            src = self.data_root()
            for path in sorted(src.rglob('*')):
                if path.is_file():
                    target = out_dir / 'Data' / path.relative_to(src)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
        files, count = 0, 0
        for rel, info in self.files():
            enc = info['encoding']
            texts = self.texts(rel, info)
            repl = {}
            for i, span in enumerate(info['spans']):
                if KIND_HINT.get(span.kind) in (None, 'protected'):
                    continue
                text = texts[i]
                if mapping.get(text, text) != text:
                    repl[i] = mapping[text]
            if not repl:
                continue
            self.check_writable(enc)
            new = wolf.rebuild(info['data'], info['spans'], repl, enc, info.get('size_at'))
            if rel.startswith('MapData/'):
                wolf.parse_map(new)
                new = wolf.map_pack(info['header'], new, info['packed'])
            (out_dir / 'Data' / rel).write_bytes(new)
            files += 1
            count += len(repl)
        self._verify(out_dir)
        return {'files': files, 'replacements': count, 'unpacked_archives': sorted(archived)}

    def _verify(self, out_dir):
        """回读构建结果，确认每个文件仍能完整解析。"""
        self.files(out_dir / 'Data')

    def launcher(self, out_dir):
        configured = self.options.get('launcher')
        if configured and (Path(out_dir) / configured).is_file():
            return configured
        exes = [p for p in sorted(Path(out_dir).glob('*.[eE][xX][eE]'))
                if not any(s in p.name.lower() for s in SKIP_EXE)]
        exes.sort(key=lambda p: p.name.lower() not in ('game.exe', 'gamepro.exe'))
        return exes[0].name if exes else None

    def probe(self, out_dir, seconds=15):
        exe = self.launcher(out_dir)
        if not exe:
            return {'skipped': '找不到 EXE'}
        return launch.probe_alive(Path(out_dir) / exe, self.ws.config.get('launch'), seconds, self.legacy_codepage)
