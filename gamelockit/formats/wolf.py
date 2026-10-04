"""WOLF RPG エディター（2.x，已用 UberWolf 等工具解出的未加密数据）的二进制数据读写。

不建完整对象模型：解析器按文件结构走一遍，只记录每个字符串的位置（长度字段偏移）与所属结构，
回写时把替换后的字符串拼回原字节并更新长度前缀；其余字节原样保留，保证未改动部分逐字节一致。
结构参考 wolftrans 0.2.1（MPL-2.0）对 Map/CommonEvent/Database/Game.dat 的描述，本文件为独立实现。
"""
import struct

MAP_MAGIC = b'\x00' * 10 + b'WOLFM\x00' + b'\x00' * 4 + b'\x64\x00\x00\x00\x65'
CE_MAGIC = b'\x00W\x00\x00OL\x00FC\x00\x8f'
DAT_MAGIC = b'\x00W\x00\x00OL\x00FM\x00'
CE_SUB_MAGIC = b'\x0a\x00\x00\x00'

# 事件命令 → 字符串参数的用途
MESSAGE, CHOICES, COMMENT, DEBUG, STRING_COND, SET_STRING, PICTURE, DATABASE = 101, 102, 103, 106, 112, 122, 150, 250


class Span:
    __slots__ = ('offset', 'size', 'raw', 'where', 'kind')

    def __init__(self, offset, size, raw, where, kind):
        self.offset, self.size, self.raw, self.where, self.kind = offset, size, raw, where, kind


class Reader:
    def __init__(self, data):
        self.data, self.pos, self.spans = data, 0, []

    def take(self, n):
        if self.pos + n > len(self.data):
            raise ValueError(f'数据在偏移 {self.pos} 处提前结束')
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def byte(self):
        return self.take(1)[0]

    def int(self):
        return struct.unpack('<i', self.take(4))[0]

    def expect(self, magic, what):
        if self.take(len(magic)) != magic:
            raise ValueError(f'{what} 标记不符（偏移 {self.pos - len(magic)}），可能是加密数据或不支持的版本')

    def string(self, where='', kind=None):
        at = self.pos
        size = self.int()
        if size <= 0 or self.pos + size > len(self.data):
            raise ValueError(f'偏移 {at} 处字符串长度异常：{size}')
        raw = self.take(size)
        if raw[-1:] != b'\x00':
            raise ValueError(f'偏移 {at} 处字符串未以 0 结尾')
        if kind:
            self.spans.append(Span(at, size, raw[:-1], where, kind))
        return raw[:-1]

    def ints(self, n):
        return [self.int() for _ in range(n)]


def _command(r, where, slot):
    argc = r.byte() - 1
    cid = r.int()
    args = r.ints(argc)
    r.byte()  # indent
    count = r.byte()
    for i in range(count):
        r.string(f'{where}/{slot}:{cid}.{i}', _command_kind(cid, args, i))
    term = r.byte()
    if term == 1:  # 移动路线
        r.take(5)
        r.byte()
        for _ in range(r.int()):
            r.byte()
            r.ints(r.byte())
            r.expect(b'\x01\x00', '路线命令结尾')
    elif term != 0:
        raise ValueError(f'命令结尾标记异常：{term}')


def _command_kind(cid, args, index):
    if cid == MESSAGE:
        return 'message'
    if cid == CHOICES:
        return 'choice'
    if cid == PICTURE and args and (args[0] >> 4) & 7 == 2 and index == 0:
        return 'picture-text'
    if cid == SET_STRING and index == 0:
        return 'set-string'
    if cid in (STRING_COND, DATABASE):
        return 'logic'
    if cid in (COMMENT, DEBUG):
        return None
    return 'other'


def _commands(r, where):
    for slot in range(r.int()):
        _command(r, where, slot)


def parse_map(body):
    """解析 map_body() 返回的正文，span 偏移相对于正文。"""
    r = Reader(body)
    r.string()
    r.int()  # tileset
    width, height = r.int(), r.int()
    r.int()  # 事件数
    if body[r.pos:r.pos + 4] == b'\xff\xff\xff\xff' and len(body) - r.pos < width * height * 12:
        r.take(4)  # 3.x 空图块占位
    else:
        r.take(width * height * 12)
    while (mark := r.byte()) == 0x6F:
        r.expect(b'\x39\x30\x00\x00', '地图事件头')
        event = r.int()
        r.string()
        r.int(), r.int()
        r.int()
        r.expect(b'\x00\x00\x00\x00', '地图事件头')
        page = 0
        while (pm := r.byte()) == 0x79:
            r.int()
            r.string()
            r.take(4 + 1 + 4 + 16 + 16 + 4 + 2)
            for _ in range(r.int()):
                r.byte()
                r.ints(r.byte())
                r.expect(b'\x01\x00', '路线命令结尾')
            _commands(r, f'ev{event}/p{page + 1}')
            r.expect(b'\x03\x00\x00\x00', '事件页命令结尾')
            r.take(3)
            # 正常为 0x7A；部分工具重写过的地图最后一页是 0x00，引擎照常加载，按原样保留
            if r.byte() not in (0x7A, 0x00):
                raise ValueError(f'事件页结尾标记异常（偏移 {r.pos - 1}）')
            page += 1
        if pm != 0x70:
            raise ValueError(f'事件页标记异常：{pm:#x}')
    if mark != 0x66 or r.pos != len(body):
        raise ValueError('地图文件结尾异常或有未解析数据')
    return r.spans


def parse_common_events(data):
    r = Reader(data)
    head = r.take(len(CE_MAGIC))
    if head[:6] != CE_MAGIC[:6] or head[7:10] != CE_MAGIC[7:10]:
        raise ValueError('公共事件文件头不符，可能是加密数据')
    for _ in range(r.int()):
        r.expect(b'\x8e', '公共事件头')
        event = r.int()
        r.int()
        r.take(7)
        r.string()
        _commands(r, f'ce{event}')
        r.string()
        r.string()  # 说明
        r.expect(b'\x8f', '公共事件数据')
        # 参数区各段都带长度；2.x 固定 10 项，3.x 为 11 项，按长度读即可兼容
        for _ in range(r.int()):
            r.string()
        r.take(r.int())
        for _ in range(r.int()):
            for _ in range(r.int()):
                r.string()
        for _ in range(r.int()):
            r.ints(r.int())
        r.ints(r.int())
        r.take(5)
        for _ in range(100):
            r.string()
        r.expect(b'\x91', '公共事件尾')
        r.string()
        mark = r.byte()
        if mark == 0x92:
            r.string()
            r.int()
            r.expect(b'\x92', '公共事件尾')
        elif mark != 0x91:
            raise ValueError(f'公共事件尾标记异常：{mark:#x}')
    if r.byte() not in (0x8F, 0x90, head[10]) or r.pos != len(data):
        raise ValueError('公共事件文件结尾异常或有未解析数据')
    return r.spans


def parse_database(project, dat, name):
    """返回 dat 中的字符串位置。只有项目文件里字段类型为 0（普通字符串）的值才算候选，
    文件名/数据库引用等特殊字段一律不列入。"""
    p = Reader(project)
    types = []
    for _ in range(p.int()):
        type_name = p.string()
        fields = [p.string() for _ in range(p.int())]
        data_names = [p.string() for _ in range(p.int())]
        p.string()
        size = p.int()
        field_types = list(p.take(size))
        for _ in range(p.int()):
            p.string()
        for _ in range(p.int()):
            for _ in range(p.int()):
                p.string()
        for _ in range(p.int()):
            p.ints(p.int())
        p.ints(p.int())
        types.append((type_name, fields, field_types, data_names))
    if p.pos != len(project):
        raise ValueError(f'{name}.project 有未解析数据')
    d = Reader(dat)
    head = d.take(len(DAT_MAGIC) + 1)
    if head[:6] != DAT_MAGIC[:6] or head[7:10] != DAT_MAGIC[7:10]:
        raise ValueError(f'{name}.dat 文件头不符，可能是加密数据')
    if d.int() != len(types):
        raise ValueError(f'{name} 的 project 与 dat 类型数不一致')
    for t, (type_name, fields, field_types, data_names) in enumerate(types):
        d.expect(b'\xfe\xff\xff\xff', '数据库类型分隔')
        d.int()
        info = d.ints(d.int())
        string_fields = [(i, v - 2000) for i, v in enumerate(info) if v >= 2000]
        int_count = len(info) - len(string_fields)
        string_fields.sort(key=lambda x: x[1])
        for row in range(d.int()):
            d.ints(int_count)
            for field, _ in string_fields:
                ftype = field_types[field] if field < len(field_types) else -1
                d.string(f'{name}/{t}/{row}/{field}', 'db' if ftype == 0 else None)
    d.expect(head[-1:], f'{name}.dat 文件尾')
    if d.pos != len(dat):
        raise ValueError(f'{name}.dat 有未解析数据')
    return d.spans, types


def parse_game_dat(data):
    """Game.dat：标题、字体名与版本说明。返回 (spans, 文件长度字段偏移或 None)。"""
    r = Reader(data)
    head = r.take(len(DAT_MAGIC))
    if head[:6] != DAT_MAGIC[:6] or head[7:9] != DAT_MAGIC[7:9]:
        raise ValueError('Game.dat 文件头不符，可能是加密数据')
    r.take(r.int())
    count = r.int()
    roles = {0: 'title', 3: 'font', 4: 'font', 5: 'font', 6: 'font', 8: 'version'}
    for i in range(count):
        if i == 2:  # 解密键，可能不以 0 结尾
            r.take(r.int())
        else:
            r.string(f'game/{i}', roles.get(i))
    size_at = r.pos
    if r.pos + 4 <= len(data) and struct.unpack_from('<i', data, r.pos)[0] == len(data) - 1:
        return r.spans, size_at
    return r.spans, None


def map_body(data):
    """返回 (文件头, 正文, 是否压缩)。3.3x 起地图正文用 LZ4 块压缩。"""
    if data[:16] != MAP_MAGIC[:16]:
        raise ValueError('地图文件头不符，可能是加密数据')
    if data[24] == 0x67:
        size, packed = struct.unpack_from('<ii', data, 25)
        try:
            import lz4.block
        except ImportError:
            raise RuntimeError('该地图为 LZ4 压缩格式，需要安装 lz4：pip install lz4') from None
        return data[:25], lz4.block.decompress(data[33:33 + packed], uncompressed_size=size), True
    if data[24] != 0x65 and data[24] != 0x66:
        raise ValueError(f'不支持的地图版本标记：{data[24]:#x}')
    return data[:25], data[25:], False


def map_pack(header, body, compressed):
    if not compressed:
        return header + body
    import lz4.block
    packed = lz4.block.compress(body, store_size=False)
    return header + struct.pack('<ii', len(body), len(packed)) + packed


def encoding_of(data, kind):
    """WOLF 3.x 文件头带 'U' 标记表示 UTF-8；否则为系统代码页（日文原版 cp932）。"""
    at = {'map': 16, 'game': 9}.get(kind, 6)
    return 'utf-8' if data[at:at + 1] == b'U' else None


def rebuild(data, spans, replacements, encoding, size_field=None):
    """replacements: {span 下标: 新文本}。返回新字节；size_field 为 Game.dat 中“文件长度-1”的偏移。"""
    out, last, shift = bytearray(), 0, 0
    for i, span in enumerate(spans):
        if i not in replacements:
            continue
        raw = replacements[i].encode(encoding) + b'\x00'
        out += data[last:span.offset] + struct.pack('<i', len(raw)) + raw
        last = span.offset + 4 + span.size
        if size_field is not None and span.offset < size_field:
            shift += len(raw) - span.size
    out += data[last:]
    if size_field is not None:
        at = size_field + shift
        out[at:at + 4] = struct.pack('<i', len(out) - 1)
    return bytes(out)
