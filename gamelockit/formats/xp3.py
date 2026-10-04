"""吉里吉里 XP3 归档读写（未加密；只读索引，按需读取条目）。

info 标志 0x80000000 只是“受保护”提示，不代表加密；是否加密以 adler32 校验为准。
"""
from dataclasses import dataclass
import struct
import zlib

MAGIC = b'XP3\r\n \n\x1a\x8bg\x01'
PROTECTED = 0x80000000


class EncryptedArchive(ValueError):
    """条目内容与校验值不符：归档被游戏专用算法加密，需先用对应工具解密。"""


@dataclass
class Entry:
    name: str
    flags: int
    size: int
    segments: list   # [(flags, offset, size, packed_size)]
    adler: int


def _index(f):
    f.seek(0)
    head = f.read(11 + 8)
    if not head.startswith(MAGIC):
        raise ValueError('不是 XP3 归档')
    offset = struct.unpack('<Q', head[11:19])[0]
    f.seek(offset)
    if f.read(1)[0] == 0x80:  # 2.28 之后的中转头：0x80 + 保留 8 字节 + 实际索引偏移
        f.read(8)
        offset = struct.unpack('<Q', f.read(8))[0]
    f.seek(offset)
    kind = f.read(1)[0]
    if kind & 1:
        packed, _ = struct.unpack('<QQ', f.read(16))
        return zlib.decompress(f.read(packed))
    size = struct.unpack('<Q', f.read(8))[0]
    return f.read(size)


def _chunks(data):
    pos = 0
    while pos + 12 <= len(data):
        tag, size = data[pos:pos + 4], struct.unpack('<Q', data[pos + 4:pos + 12])[0]
        yield tag, data[pos + 12:pos + 12 + size]
        pos += 12 + size


def entries(path):
    with open(path, 'rb') as f:
        index = _index(f)
    result = []
    for tag, body in _chunks(index):
        if tag != b'File':
            continue
        info = segs = adler = None
        for sub, data in _chunks(body):
            if sub == b'info':
                flags, size, _, length = struct.unpack('<LQQH', data[:22])
                info = (data[22:22 + length * 2].decode('utf-16le'), flags, size)
            elif sub == b'segm':
                segs = [struct.unpack('<LQQQ', data[i:i + 28]) for i in range(0, len(data), 28)]
            elif sub == b'adlr':
                adler = struct.unpack('<L', data[:4])[0]
        if info and segs is not None:
            result.append(Entry(info[0], info[1], info[2], segs, adler))
    return result


def read_entry(f, entry):
    data = b''.join(_segment(f, seg) for seg in entry.segments)
    if entry.adler is not None and zlib.adler32(data) != entry.adler:
        raise EncryptedArchive(f'{entry.name}: 校验不符，归档可能已加密')
    return data


def _segment(f, seg):
    flags, offset, _, packed = seg
    f.seek(offset)
    raw = f.read(packed)
    if flags & 7:
        try:
            return zlib.decompress(raw)
        except zlib.error as exc:
            raise EncryptedArchive(f'段解压失败，归档可能已加密: {exc}') from exc
    return raw


def read(path, want=None):
    """返回 {条目名: bytes}；want 为过滤函数。"""
    with open(path, 'rb') as f:
        return {e.name: read_entry(f, e) for e in entries(path) if want is None or want(e.name)}


def write(path, files):
    """写出新归档（zlib 压缩、未加密）。files: {条目名: bytes}。"""
    body, index = bytearray(), bytearray()
    start = 11 + 8
    for name, data in files.items():
        packed = zlib.compress(data, 9)
        offset = start + len(body)
        body += packed
        encoded = name.encode('utf-16le')
        info = struct.pack('<LQQH', 0, len(data), len(packed), len(name)) + encoded
        segm = struct.pack('<LQQQ', 1, offset, len(data), len(packed))
        adlr = struct.pack('<L', zlib.adler32(data))
        chunk = b''.join(tag + struct.pack('<Q', len(v)) + v for tag, v in ((b'info', info), (b'segm', segm), (b'adlr', adlr)))
        index += b'File' + struct.pack('<Q', len(chunk)) + chunk
    index_offset = start + len(body)
    packed_index = zlib.compress(bytes(index), 9)
    with open(path, 'wb') as f:
        f.write(MAGIC + struct.pack('<Q', index_offset))
        f.write(body)
        f.write(b'\x01' + struct.pack('<QQ', len(packed_index), len(index)) + packed_index)
