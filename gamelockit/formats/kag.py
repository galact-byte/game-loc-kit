"""KAG / TyranoScript 剧本（.ks）的文字单元识别与原位替换（吉里吉里与 Tyrano 共用）。"""
import re

TAG = re.compile(r'\[[^\]\n]*\]')
ATTR = re.compile(r'''\b(text|jname)\s*=\s*("([^"]*)"|'([^']*)'|([^\s\]"']+))''')
CODE_BLOCKS = (('[iscript]', '[endscript]'), ('[html]', '[endhtml]'), ('@iscript', '@endscript'))


def scenario_units(text):
    """产出 (行号, 类别, 起, 止, 原文)；起止为该行内的字符区间，便于原位替换。"""
    in_code = None
    for n, line in enumerate(text.split('\n')):
        stripped = line.strip()
        low = stripped.lower()
        if in_code:
            if low.startswith(in_code):
                in_code = None
            continue
        opened = next((end for start, end in CODE_BLOCKS if low.startswith(start)), None)
        if opened and opened not in low:
            in_code = opened
            continue
        if not stripped or stripped[0] in ';*@':
            continue
        lead = len(line) - len(line.lstrip())
        body = line.rstrip('\r').rstrip()
        if stripped[0] == '#':
            name = body[lead + 1:]
            if name.strip():
                yield n, 'speaker', lead + 1, len(body), name
            continue
        visible = TAG.sub('', stripped)
        if visible.strip():
            yield n, 'text', lead, len(body), body[lead:]
            continue
        for tag in TAG.finditer(body):
            for m in ATTR.finditer(tag.group(0)):
                group = 3 if m.group(3) is not None else 4 if m.group(4) is not None else 5
                start = tag.start() + m.start(group)
                yield n, f'attr:{m.group(1)}', start, start + len(m.group(group)), m.group(group)


def apply_units(text, mapping):
    lines = text.split('\n')
    changes = {}
    for n, _, start, end, source in scenario_units(text):
        target = mapping.get(source)
        if target is not None and target != source:
            changes.setdefault(n, []).append((start, end, target))
    for n, edits in changes.items():
        line = lines[n]
        for start, end, target in sorted(edits, reverse=True):
            line = line[:start] + target + line[end:]
        lines[n] = line
    return '\n'.join(lines), sum(len(v) for v in changes.values())
