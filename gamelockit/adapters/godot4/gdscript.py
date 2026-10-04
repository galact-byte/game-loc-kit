"""GDScript 4 编译脚本（GDSC v101）读写：提取字符串常量、改常量池、在显示消费点插入 tr()。

不重新编译脚本；任何改动后都重新解析并核对标识符表与 Token 流，结构变化即拒绝。
"""
from collections import Counter, defaultdict
import json as _json
import struct


def _zstd_decompress(data, size):
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
    except ImportError:
        pass
    try:
        import pyarrow as pa
        return pa.decompress(data, decompressed_size=size, codec='zstd').to_pybytes()
    except ImportError as error:
        raise RuntimeError('解析压缩的 .gdc 需要 zstandard 或 pyarrow：pip install zstandard') from error


NAMES = '''EMPTY ANNOTATION IDENTIFIER LITERAL LESS LESS_EQUAL GREATER GREATER_EQUAL EQUAL_EQUAL BANG_EQUAL AND OR NOT AMPERSAND_AMPERSAND PIPE_PIPE BANG AMPERSAND PIPE TILDE CARET LESS_LESS GREATER_GREATER PLUS MINUS STAR STAR_STAR SLASH PERCENT EQUAL PLUS_EQUAL MINUS_EQUAL STAR_EQUAL STAR_STAR_EQUAL SLASH_EQUAL PERCENT_EQUAL LESS_LESS_EQUAL GREATER_GREATER_EQUAL AMPERSAND_EQUAL PIPE_EQUAL CARET_EQUAL IF ELIF ELSE FOR WHILE BREAK CONTINUE PASS RETURN MATCH WHEN AS ASSERT AWAIT BREAKPOINT CLASS CLASS_NAME TK_CONST ENUM EXTENDS FUNC TK_IN IS NAMESPACE PRELOAD SELF SIGNAL STATIC SUPER TRAIT VAR TK_VOID YIELD BRACKET_OPEN BRACKET_CLOSE BRACE_OPEN BRACE_CLOSE PARENTHESIS_OPEN PARENTHESIS_CLOSE COMMA SEMICOLON PERIOD PERIOD_PERIOD PERIOD_PERIOD_PERIOD COLON DOLLAR FORWARD_ARROW UNDERSCORE NEWLINE INDENT DEDENT CONST_PI CONST_TAU CONST_INF CONST_NAN VCS_CONFLICT_MARKER BACKTICK QUESTION_MARK ERROR TK_EOF TK_MAX'''.split()
SYMBOLS = dict(zip('LESS LESS_EQUAL GREATER GREATER_EQUAL EQUAL_EQUAL BANG_EQUAL AMPERSAND_AMPERSAND PIPE_PIPE BANG AMPERSAND PIPE TILDE CARET LESS_LESS GREATER_GREATER PLUS MINUS STAR STAR_STAR SLASH PERCENT EQUAL PLUS_EQUAL MINUS_EQUAL STAR_EQUAL STAR_STAR_EQUAL SLASH_EQUAL PERCENT_EQUAL LESS_LESS_EQUAL GREATER_GREATER_EQUAL AMPERSAND_EQUAL PIPE_EQUAL CARET_EQUAL BRACKET_OPEN BRACKET_CLOSE BRACE_OPEN BRACE_CLOSE PARENTHESIS_OPEN PARENTHESIS_CLOSE COMMA SEMICOLON PERIOD PERIOD_PERIOD PERIOD_PERIOD_PERIOD COLON DOLLAR FORWARD_ARROW UNDERSCORE'.split(), '< <= > >= == != && || ! & | ~ ^ << >> + - * ** / % = += -= *= **= /= %= <<= >>= &= |= ^= [ ] { } ( ) , ; . .. ... : $ -> _'.split()))
KIND = {name: index for index, name in enumerate(NAMES)}
# 显示消费函数 → 文字参数位置
DISPLAY_CALLS = {'draw_string': 2, 'draw_multiline_string': 2, 'get_string_size': 0, 'get_multiline_string_size': 0}


def parse_gdc(data):
    if len(data) < 12 or data[:4] != b'GDSC':
        raise ValueError('GDSC 头部无效')
    version, size = struct.unpack_from('<II', data, 4)
    if version != 101:
        raise ValueError('不支持的 GDSC 版本')
    body = _zstd_decompress(data[12:], size) if size else data[12:]
    if len(body) < 16:
        raise ValueError('常量表截断')
    ids, constants, lines, tokens = struct.unpack_from('<4I', body)
    pos = 16
    identifiers = []
    strings = []
    def u32(offset):
        if offset + 4 > len(body):
            raise ValueError('数据截断')
        return struct.unpack_from('<I', body, offset)[0]
    for _ in range(ids):
        length = u32(pos)
        pos += 4
        end = pos + length * 4
        if end > len(body):
            raise ValueError('标识符截断')
        identifiers.append(bytes(x ^ 0xb6 for x in body[pos:end]).decode('utf-32-le'))
        pos = end
    for index in range(constants):
        start = pos
        header = u32(pos)
        kind = header & 0xffff
        pos += 4
        if kind == 0:
            pass
        elif kind == 1:
            pos += 4
        elif kind in (2, 3):
            pos += 8 if header & (1 << 16) else 4
        elif kind in (4, 21):
            length = u32(pos)
            text = body[pos + 4:pos + 4 + length].decode('utf-8')
            pos += 4 + (length + 3) // 4 * 4
            strings.append({'index': index, 'text': text, 'start': start, 'end': pos, 'kind': kind})
        else:
            raise ValueError(f'不支持的常量类型 {kind}')
        if pos > len(body):
            raise ValueError('常量截断')
    tail = pos
    pos += lines * 16
    for _ in range(tokens):
        if pos >= len(body):
            raise ValueError('Token 截断')
        pos += 8 if body[pos] & 0x80 else 5
    if pos != len(body):
        raise ValueError('Token 长度不匹配')
    return {'body': body, 'strings': strings, 'identifiers': identifiers, 'tail': tail, 'version': version}


def patch_gdc(data, replacements):
    if not replacements:
        return data
    parsed = parse_gdc(data)
    body = parsed['body']
    parts = []
    pos = 0
    applied = set()
    for item in parsed['strings']:
        if item['index'] not in replacements:
            continue
        target = replacements[item['index']].encode('utf-8')
        parts.extend([body[pos:item['start']], struct.pack('<II', item['kind'], len(target)), target, bytes((-len(target)) % 4)])
        pos = item['end']
        applied.add(item['index'])
    if applied != set(replacements):
        raise ValueError('试图修改非字符串常量')
    parts.append(body[pos:])
    result = b'GDSC' + struct.pack('<II', parsed['version'], 0) + b''.join(parts)
    check = parse_gdc(result)
    if check['body'][check['tail']:] != body[parsed['tail']:] or check['identifiers'] != parsed['identifiers']:
        raise ValueError('脚本结构被改变')
    return result


def call_arguments(tokens, opening):
    pairs = {KIND['PARENTHESIS_OPEN']: KIND['PARENTHESIS_CLOSE'],
             KIND['BRACKET_OPEN']: KIND['BRACKET_CLOSE'],
             KIND['BRACE_OPEN']: KIND['BRACE_CLOSE']}
    stack = [KIND['PARENTHESIS_CLOSE']]
    start = opening + 1
    args = []
    for index in range(start, len(tokens)):
        kind = tokens[index][0] & 127
        if kind in pairs:
            stack.append(pairs[kind])
        elif kind in pairs.values():
            if not stack or stack.pop() != kind:
                raise ValueError('绘制调用的括号不匹配')
            if not stack:
                args.append((start, index))
                return args
        elif kind == KIND['COMMA'] and len(stack) == 1:
            args.append((start, index))
            start = index + 1
    raise ValueError('绘制调用缺少闭括号')


def patch_display_calls(data, calls=None, prefix_receivers=()):
    calls = DISPLAY_CALLS if calls is None else calls
    parsed = parse_gdc(data)
    body = parsed['body']
    ids, constants, lines, count = struct.unpack_from('<4I', body)
    identifiers = parsed['identifiers']
    pos = parsed['tail'] + lines * 16
    tokens = []
    for _ in range(count):
        wide = bool(body[pos] & 128)
        token = struct.unpack_from('<I', body, pos)[0] if wide else body[pos]
        pos += 4 if wide else 1
        tokens.append((token, struct.unpack_from('<I', body, pos)[0]))
        pos += 4
    openings, closings = defaultdict(list), defaultdict(list)
    counts = Counter()
    tr_id = identifiers.index('tr') if 'tr' in identifiers else ids
    for index, (token, line) in enumerate(tokens[:-3]):
        if (token & 127 == KIND['IDENTIFIER'] and identifiers[token >> 8] in prefix_receivers
                and tokens[index + 1][0] & 127 == KIND['PERIOD']
                and tokens[index + 2][0] & 127 == KIND['IDENTIFIER']
                and identifiers[tokens[index + 2][0] >> 8] == 'left'
                and tokens[index + 3][0] & 127 == KIND['PARENTHESIS_OPEN']):
            openings[index].extend([(KIND['IDENTIFIER'] | (tr_id << 8), line), (KIND['PARENTHESIS_OPEN'], line)])
            closings[index + 1].append((KIND['PARENTHESIS_CLOSE'], line))
            counts['initial'] += 1
    for index, (token, _) in enumerate(tokens[:-1]):
        if token & 127 != KIND['IDENTIFIER'] or tokens[index + 1][0] & 127 != KIND['PARENTHESIS_OPEN']:
            continue
        name = identifiers[token >> 8]
        if name not in calls or (index and tokens[index - 1][0] & 127 == KIND['FUNC']):
            continue
        args = call_arguments(tokens, index + 1)
        if len(args) <= calls[name]:
            raise ValueError('绘制调用缺少预期文字参数')
        start, end = args[calls[name]]
        if start == end:
            raise ValueError('绘制调用的文字参数为空')
        if (tokens[start][0] & 127 == KIND['IDENTIFIER'] and tokens[start][0] >> 8 == tr_id
                and start + 1 < end and tokens[start + 1][0] & 127 == KIND['PARENTHESIS_OPEN']
                and call_arguments(tokens, start + 1)[-1][1] == end - 1):
            continue
        line = tokens[start][1]
        openings[start].extend([(KIND['IDENTIFIER'] | (tr_id << 8), line), (KIND['PARENTHESIS_OPEN'], line)])
        closings[end].append((KIND['PARENTHESIS_CLOSE'], tokens[end - 1][1]))
        counts[name] += 1
    if not counts:
        return data, {}
    rewritten = []
    relocated = {}
    for index in range(count + 1):
        rewritten.extend(closings[index])
        relocated[index] = len(rewritten)
        rewritten.extend(openings[index])
        if index < count:
            rewritten.append(tokens[index])
    ids_end = 16 + sum(4 + len(name.encode('utf-32-le')) for name in identifiers)
    pool = body[16:ids_end]
    if tr_id == ids:
        encoded = 'tr'.encode('utf-32-le')
        pool += struct.pack('<I', len(encoded) // 4) + bytes(x ^ 0xb6 for x in encoded)
        ids += 1
    pool += body[ids_end:parsed['tail']]
    tables = bytearray()
    for index in range(lines * 2):
        old_index, value = struct.unpack_from('<II', body, parsed['tail'] + index * 8)
        if old_index not in relocated:
            raise ValueError('脚本行表索引越界')
        tables.extend(struct.pack('<II', relocated[old_index], value))
    stream = b''.join(struct.pack('<II', token | 128, line) for token, line in rewritten)
    result = b'GDSC' + struct.pack('<II', parsed['version'], 0)
    result += struct.pack('<4I', ids, constants, lines, len(rewritten)) + pool + tables + stream
    check = parse_gdc(result)
    if [s['text'] for s in check['strings']] != [s['text'] for s in parsed['strings']]:
        raise ValueError('绘制补丁意外改变了原始文字')
    return result, dict(counts)


def render(data):
    """把 Token 流还原成近似源码行，供用途审核查看字符串在哪里被使用。"""
    parsed = parse_gdc(data)
    body = parsed['body']
    _, count, line_count, token_count = struct.unpack_from('<4I', body)
    constants = {s['index']: s['text'] for s in parsed['strings']}
    line_columns = {}
    tail = parsed['tail']
    for i in range(line_count):
        idx, line = struct.unpack_from('<II', body, tail + i * 8)
        _, column = struct.unpack_from('<II', body, tail + line_count * 8 + i * 8)
        line_columns[line] = column
    pos = tail + line_count * 16
    lines = defaultdict(list)
    uses = defaultdict(set)
    for _ in range(token_count):
        if body[pos] & 0x80:
            token = struct.unpack_from('<I', body, pos)[0]
            pos += 4
        else:
            token = body[pos]
            pos += 1
        line = struct.unpack_from('<I', body, pos)[0]
        pos += 4
        kind = token & 127
        idx = token >> 8
        name = NAMES[kind]
        if name in ('IDENTIFIER', 'ANNOTATION'):
            text = ('@' if name == 'ANNOTATION' else '') + parsed['identifiers'][idx]
        elif name in ('LITERAL', 'ERROR'):
            text = _json.dumps(constants[idx], ensure_ascii=False) if idx in constants else f'NUM_{idx}'
            if idx in constants:
                uses[idx].add(line)
        else:
            text = SYMBOLS.get(name, name.removeprefix('TK_').lower())
        lines[line].append(text)
    rendered = {line: ' ' * min(line_columns.get(line, 1) - 1, 80) + ' '.join(tokens) for line, tokens in lines.items()}
    usage = {idx: [rendered[line] for line in sorted(used)] for idx, used in uses.items()}
    return rendered, usage
