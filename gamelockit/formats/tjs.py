"""TJS 脚本中的字符串字面量定位（跳过注释；@"…" 内嵌表达式字符串不处理）。"""
import re

ESCAPE = r'\\[\\\'"abfnrtv0]|\\x[0-9A-Fa-f]+'


def string_literals(text):
    """产出 (起, 止, 引号, 内容原文)；起止为引号内内容的字符区间，内容保留转义序列原样。"""
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if text.startswith('//', i):
            i = text.find('\n', i)
            i = n if i < 0 else i
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            i = n if end < 0 else end + 2
        elif ch in '"\'':
            embedded = i > 0 and text[i - 1] == '@'
            j = i + 1
            while j < n and text[j] != ch and text[j] != '\n':
                j += 2 if text[j] == '\\' else 1
            if j < n and text[j] == ch and not embedded:
                yield i + 1, j, ch, text[i + 1:j]
            i = j + 1
        else:
            i += 1


def safe_literal(target, quote):
    """译文放回字面量前的检查：不得含未转义的同种引号或换行。"""
    if '\n' in target or '\r' in target:
        return False
    return re.search(r'(?<!\\)(?:\\\\)*' + re.escape(quote), target) is None


def apply_literals(text, mapping, allowed=None):
    """替换在 mapping 中的字面量内容；allowed(内容) 返回 False 时跳过。"""
    edits = []
    for start, end, quote, content in string_literals(text):
        target = mapping.get(content)
        if target is None or target == content or (allowed and not allowed(content)):
            continue
        if not safe_literal(target, quote):
            raise ValueError(f'译文含未转义引号或换行，无法放回 TJS 字面量（偏移 {start}）')
        edits.append((start, end, target))
    for start, end, target in reversed(edits):
        text = text[:start] + target + text[end:]
    return text, len(edits)
