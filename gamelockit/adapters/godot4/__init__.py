"""Godot 4 适配器：显示层注入。

原文、脚本常量、存档值一律不改；在 PCK 中加入一个自动加载节点，向 TranslationServer 注册
自定义 Translation，所有控件在显示时把原文换成译文。自绘文字（draw_string 等）在消费点插入 tr()。
"""
import json
from pathlib import Path
import re
import subprocess

from .. import register
from ... import saveguard
from ..base import Adapter, Occurrence, copy_tree
from ...textutil import is_candidate
from . import gdscript, pck, settings
from .messages import compile_messages

RUNTIME = Path(__file__).with_name('runtime')
SCENE_TEXT = re.compile(r'^(text|tooltip_text|placeholder_text|title|dialog_text|ok_button_text|cancel_button_text)\s*=\s*"((?:[^"\\]|\\.)*)"', re.M | re.S)
GD_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'')
BINARY_STRING = re.compile(rb'(?s)(.{4})')


def _unescape(text):
    return text.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')


def _json_strings(value, lang, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _json_strings(child, lang, path + (str(key),))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _json_strings(child, lang, path + (str(i),))
    elif isinstance(value, str) and is_candidate(value, lang):
        yield '/'.join(path), value


def _binary_strings(data, lang, min_len=2):
    """Godot 二进制资源（.scn/.res）里的 u32 长度前缀 UTF-8 字符串。"""
    pos, end = 0, len(data) - 4
    while pos < end:
        length = int.from_bytes(data[pos:pos + 4], 'little')
        if min_len <= length <= 4096 and pos + 4 + length <= len(data):
            raw = data[pos + 4:pos + 4 + length].rstrip(b'\0')
            try:
                text = raw.decode('utf-8')
            except UnicodeDecodeError:
                text = None
            if text and text.isprintable() or (text and '\n' in text):
                if is_candidate(text, lang):
                    yield pos, text
                    pos += 4 + length
                    continue
        pos += 1


@register
class Godot4Adapter(Adapter):
    name = 'godot4'
    title = 'Godot 4（PCK，独立或内嵌 EXE）'
    display_layer = True
    token_patterns = (r'\[/?[a-z_]+(?:[= ][^\]\n]*)?\]',)
    translator_notes = ('- Godot BBCode 标签（如 [color=#fff]…[/color]、[b]、[url=…]）及其属性原样保留，只翻译标签之间的文字。\n'
                        '- `{name}` 形式的占位符原样保留，可以按中文语序移动位置。')

    @classmethod
    def detect(cls, game_dir):
        game_dir = Path(game_dir)
        if any(game_dir.glob('*.pck')):
            return 90
        for exe in game_dir.glob('*.exe'):
            if exe.stat().st_size > 20_000_000:
                with exe.open('rb') as f:
                    head = f.read(4096)
                    f.seek(-12, 2)
                    tail = f.read(12)
                if tail.endswith(b'GDPC'):
                    return 95
                data = exe.read_bytes()
                sec = pck.pe_section(data)
                if sec and data[sec[1]:sec[1] + 4] == b'GDPC':
                    return 95
                del head
        return 0

    # ---- 定位与解包 ----
    def source_file(self):
        configured = self.options.get('pack')
        if configured:
            return self.game / configured
        packs = sorted(self.game.glob('*.pck'))
        if packs:
            return packs[0]
        for exe in sorted(self.game.glob('*.exe'), key=lambda p: p.stat().st_size, reverse=True):
            try:
                pck.locate(exe.read_bytes())
                return exe
            except ValueError:
                continue
        raise FileNotFoundError('找不到 PCK 或内嵌 PCK 的 EXE')

    def key(self, data):
        opt = self.options
        if opt.get('key'):
            return bytes.fromhex(opt['key'])
        if opt.get('key_offset') is not None:
            return data[opt['key_offset']:opt['key_offset'] + 32]
        start = pck.locate(data)
        if not pck.header(data, start)['flags'] & pck.PACK_DIR_ENCRYPTED:
            return None
        offset = pck.find_key(data)
        if offset is None:
            raise ValueError('PCK 已加密且未能自动找到密钥；请在 glk.json 的 adapter.key 填写 64 位十六进制密钥')
        self.ws.config['adapter']['key_offset'] = offset
        self.ws.save()
        return data[offset:offset + 32]

    def unpack(self):
        marker = self.ws.unpacked / '.glk-unpacked.json'
        if marker.exists():
            return
        data = self.source_file().read_bytes()
        files, info = pck.read_pack(data, self.key(data))
        for path, content in files.items():
            dest = self.ws.unpacked / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        info = {k: v for k, v in info.items() if k != 'start'}
        marker.write_text(json.dumps(info), encoding='utf-8')

    def files(self):
        root = self.ws.unpacked
        return {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file() and p.name != '.glk-unpacked.json'}

    # ---- 提取 ----
    def extract(self):
        lang = self.ws.source_lang
        for rel, path in sorted(self.files().items()):
            suffix = path.suffix.lower()
            if suffix == '.json':
                try:
                    value = json.loads(path.read_text(encoding='utf-8-sig'))
                except (ValueError, UnicodeDecodeError):
                    continue
                for jpath, text in _json_strings(value, lang):
                    yield Occurrence(text, 'json', f'{rel}#{jpath}', jpath.rsplit('/', 1)[-1])
            elif suffix == '.gdc':
                yield from self._gdc(rel, path.read_bytes(), lang)
            elif suffix == '.gd':
                for n, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    for m in GD_STRING.finditer(line):
                        text = _unescape(m.group(1) if m.group(1) is not None else m.group(2))
                        if is_candidate(text, lang):
                            yield Occurrence(text, 'script', f'{rel}:{n}', line.strip()[:200])
            elif suffix in ('.tscn', '.tres'):
                for m in SCENE_TEXT.finditer(path.read_text(encoding='utf-8', errors='replace')):
                    text = _unescape(m.group(2))
                    if is_candidate(text, lang):
                        # 场景控件的显示属性：由引擎自动翻译显示，内部值不变。
                        yield Occurrence(text, 'scene', f'{rel}#{m.group(1)}', m.group(1), 'display')
            elif suffix in ('.scn', '.res'):
                data = path.read_bytes()
                if data[:4] == b'RSRC':
                    for pos, text in _binary_strings(data, lang):
                        yield Occurrence(text, 'binary-resource', f'{rel}@{pos}', '')

    def _gdc(self, rel, data, lang):
        try:
            parsed = gdscript.parse_gdc(data)
            _, usage = gdscript.render(data)
        except (ValueError, RuntimeError) as error:
            yield Occurrence(f'<无法解析 {rel}: {error}>', 'error', rel, '', 'excluded')
            return
        for s in parsed['strings']:
            if is_candidate(s['text'], lang):
                uses = ' | '.join(line.strip()[:160] for line in usage.get(s['index'], [])[:3])
                yield Occurrence(s['text'], 'script', f'{rel}#const{s["index"]}', uses)

    # ---- 构建 ----
    def build(self, mapping, out_dir):
        out_dir = Path(out_dir)
        source = self.source_file()
        original = source.read_bytes()
        files = {rel: path.read_bytes() for rel, path in self.files().items()}
        draw = {}
        mode = self.options.get('draw_patch', 'auto')
        receivers = self.options.get('prefix_receivers', {})
        targets = sorted(files) if mode == 'auto' else list(mode or [])
        for rel in targets:
            if not rel.endswith('.gdc'):
                continue
            try:
                files[rel], counts = gdscript.patch_display_calls(files[rel], prefix_receivers=tuple(receivers.get(rel, ())))
            except (ValueError, RuntimeError) as error:
                draw[rel] = {'error': str(error)}
                continue
            if counts:
                draw[rel] = counts
        overrides = self.ws.path('overrides')
        replaced = []
        if overrides.exists():
            for path in sorted(p for p in overrides.rglob('*') if p.is_file()):
                rel = path.relative_to(overrides).as_posix()
                if rel not in files:
                    raise ValueError(f'覆盖资源在原包中不存在: {rel}')
                files[rel] = path.read_bytes()
                replaced.append(rel)
        data = compile_messages(mapping, self.options.get('message_aliases', ()))
        data['prefixes'] = self.options.get('prefixes', [])
        files['glk_patch/messages.json'] = json.dumps(data, ensure_ascii=False).encode('utf-8')
        files['glk_patch/glk_locale.gd'] = (RUNTIME / 'glk_locale.gd').read_bytes()
        files['glk_patch/glk_display_translation.gd'] = (RUNTIME / 'glk_display_translation.gd').read_bytes()
        changes = {'autoload/GlkDisplay': settings.string_variant('*res://glk_patch/glk_locale.gd')}
        if self.options.get('separate_saves', True):
            name = settings.read_string(files['project.binary'], 'application/config/name') or source.stem
            changes['application/config/use_custom_user_dir'] = settings.bool_variant(True)
            changes['application/config/custom_user_dir_name'] = settings.string_variant(f'{name}-zh')
        files['project.binary'] = settings.patch_settings(files['project.binary'], changes)
        info = pck.header(original, pck.locate(original))
        pack = pck.build_pack(files, info['engine'])
        copy_tree(self.game, out_dir, exclude=(*self.personal_data_globs, source.name))
        if source.suffix.lower() == '.pck':
            (out_dir / source.name).write_bytes(pack)
        else:
            (out_dir / source.name).write_bytes(pck.embed(original, pack))
        return {'messages': len(mapping), 'rules': len(data['rules']), 'draw_patches': draw, 'overrides': replaced, 'output': source.name}

    def shared_save_locations(self, out_dir):
        # Godot 的 user:// 在游戏目录外（%APPDATA%）；原版目录和汉化版自己的 -zh 目录都可能已有玩家进度。
        project = self.ws.unpacked / 'project.binary'
        if not project.is_file():
            raise RuntimeError('尚未解包，无法定位共用存档，拒绝自动启动')
        data = project.read_bytes()
        name = settings.read_string(data, 'application/config/name') or self.source_file().stem
        names = {f'Godot/app_userdata/{name}', f'{name}-zh'}
        custom = settings.read_string(data, 'application/config/custom_user_dir_name')
        if custom:
            names.add(custom)
        return [('dir', saveguard.appdata(*n.split('/'))) for n in sorted(names)]

    def launcher(self, out_dir):
        source = self.source_file()
        if source.suffix.lower() == '.exe':
            return source.name
        exes = sorted(Path(out_dir).glob('*.exe'))
        return exes[0].name if exes else None

    def probe(self, out_dir, timeout=60):
        exe = Path(out_dir) / (self.launcher(out_dir) or '')
        if not exe.is_file():
            return {'skipped': '找不到可执行文件'}
        args = [str(exe), '--headless', '--quit-after', '600']
        if self.source_file().suffix.lower() == '.pck':
            args += ['--main-pack', str(Path(out_dir) / self.source_file().name)]
        args += ['--', '--glk-probe']
        try:
            run = subprocess.run(args, capture_output=True, timeout=timeout, cwd=out_dir)
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': f'{timeout} 秒内未退出'}
        out = (run.stdout + run.stderr).decode('utf-8', 'replace')
        ready = re.search(r'GLK_DISPLAY_READY (\d+)', out)
        errors = [line for line in out.splitlines() if 'SCRIPT ERROR' in line or 'glk_patch' in line and 'ERROR' in line]
        return {'ok': bool(ready) and not errors, 'exit_code': run.returncode, 'dictionary_entries': int(ready.group(1)) if ready else None, 'script_errors': errors[:10]}
