"""截图文字识别：调用 Windows 自带 OCR（templates/ocr.ps1），不依赖额外软件。"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

SCRIPT = Path(__file__).with_name('templates') / 'ocr.ps1'
# Windows OCR 会在中日文字之间插入空格；去掉后才能与原文片段比对。
CJK_GAP = re.compile(r'(?<=[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]) (?=[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef])')


def recognize(images, lang):
    """返回 {图片路径: [行文字]}；识别失败的图片对应 {'error': 说明}。"""
    images = [str(Path(p)) for p in images]
    if not images:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        listing, out = Path(tmp, 'list.txt'), Path(tmp, 'ocr.jsonl')
        listing.write_text('\n'.join(images), encoding='utf-8')
        done = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(SCRIPT),
                               '-List', str(listing), '-Lang', lang, '-Out', str(out)],
                              capture_output=True, timeout=60 + 20 * len(images))
        if done.returncode or not out.is_file():
            raise RuntimeError('OCR 失败：' + done.stderr.decode('utf-8', 'replace').strip()[-500:])
        result = {}
        for line in out.read_text(encoding='utf-8-sig').splitlines():
            row = json.loads(line)
            result[row['file']] = {'error': row['error']} if 'error' in row else [CJK_GAP.sub('', t) for t in row['lines']]
        return result


WORD_CHAR = re.compile(r'[\u3041-\u30ff\u3400-\u9fff\uac00-\ud7af]|[A-Za-z]{2,}')


def text_lines(recognized, min_units=2):
    """汇总各图的识别行，丢掉少于 min_units 个文字单元的碎片（多为图标/花纹被误识别，避免误报）。"""
    return [t for lines in recognized.values() if isinstance(lines, list)
            for t in lines if len(WORD_CHAR.findall(t)) >= min_units]
