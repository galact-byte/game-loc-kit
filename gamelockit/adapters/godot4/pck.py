"""Godot 4 PCK 读写：支持独立 .pck 与内嵌 EXE、可选 AES-256-CFB 加密（需密钥）。

只读解包；写入时生成新的未加密 PCK（v2），嵌入到 EXE 副本或作为独立 .pck。
"""
import hashlib
from pathlib import PurePosixPath
import struct

PACK_DIR_ENCRYPTED = 1
PACK_REL_FILEBASE = 2
FILE_ENCRYPTED = 1
FILE_REMOVAL = 2


def safe_relative(path):
    path = path.removeprefix('res://')
    p = PurePosixPath(path)
    if not path or p.is_absolute() or '..' in p.parts or ':' in path or '\\' in path:
        raise ValueError(f'不安全资源路径: {path[:80]}')
    return str(p)


def pe_section(data, name=b'pck'):
    """返回内嵌 PCK 节 (节头偏移, 数据偏移, 大小)；非 PE 或无该节返回 None。"""
    if data[:2] != b'MZ' or len(data) < 64:
        return None
    pe = struct.unpack_from('<I', data, 60)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        return None
    count = struct.unpack_from('<H', data, pe + 6)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    found = []
    for i in range(count):
        pos = pe + 24 + opt + i * 40
        if data[pos:pos + 8].rstrip(b'\0') == name:
            size, start = struct.unpack_from('<II', data, pos + 16)
            found.append((pos, start, size))
    return found[0] if len(found) == 1 else None


def locate(data):
    """找到 PCK 起点：独立 .pck 为 0；EXE 优先 pck 节，再看文件尾的 GDPC 魔数。"""
    if data[:4] == b'GDPC':
        return 0
    sec = pe_section(data)
    if sec and data[sec[1]:sec[1] + 4] == b'GDPC':
        return sec[1]
    if data[-4:] == b'GDPC':
        size = struct.unpack_from('<Q', data, len(data) - 12)[0]
        start = len(data) - 12 - size
        if 0 <= start and data[start:start + 4] == b'GDPC':
            return start
    raise ValueError('未找到 Godot PCK')


def decrypt_block(data, offset, key):
    from Crypto.Cipher import AES
    if offset < 0 or offset + 40 > len(data):
        raise ValueError('加密头截断')
    digest = data[offset:offset + 16]
    length = struct.unpack_from('<Q', data, offset + 16)[0]
    end = offset + 40 + (length + 15) // 16 * 16
    if end > len(data):
        raise ValueError('加密数据截断')
    iv = data[offset + 24:offset + 40]
    plain = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(data[offset + 40:end])[:length]
    if hashlib.md5(plain).digest() != digest:
        raise ValueError('解密 MD5 校验失败（密钥错误？）')
    return plain


def header(data, start):
    magic, version, major, minor, patch = struct.unpack_from('<4s4I', data, start)
    if magic != b'GDPC':
        raise ValueError('PCK 魔数错误')
    if version < 2:
        raise ValueError(f'PCK 版本 {version} 属于 Godot 3，不受本适配器支持')
    flags, base = struct.unpack_from('<IQ', data, start + 20)
    if version >= 3:
        directory = start + struct.unpack_from('<Q', data, start + 32)[0]
    else:
        directory = start + 32 + 64
    if flags & PACK_REL_FILEBASE:
        base += start
    return {'version': version, 'engine': (major, minor, patch), 'flags': flags, 'base': base, 'directory': directory}


def find_key(data, step=4):
    """在 EXE 的已初始化数据中搜索能解开加密目录的 32 字节密钥。

    每个候选只做一次 AES 块运算，看首个路径长度与字符是否合理，再用完整 MD5 确认，避免误报。
    """
    from Crypto.Cipher import AES
    start = locate(data)
    h = header(data, start)
    if not h['flags'] & PACK_DIR_ENCRYPTED:
        return None
    enc = h['directory'] + 4
    iv = data[enc + 24:enc + 40]
    first = data[enc + 40:enc + 56]
    pe = struct.unpack_from('<I', data, 60)[0]
    count = struct.unpack_from('<H', data, pe + 6)[0]
    opt = struct.unpack_from('<H', data, pe + 20)[0]
    ranges = []
    for i in range(count):
        pos = pe + 24 + opt + i * 40
        name = data[pos:pos + 8].rstrip(b'\0')
        raw_size, raw_ptr = struct.unpack_from('<II', data, pos + 16)
        if name in (b'.data', b'.rdata'):
            ranges.append((raw_ptr, raw_ptr + raw_size))
    for lo, hi in ranges:
        for off in range(lo - lo % step, hi - 32, step):
            key = data[off:off + 32]
            if key.count(0) > 8:
                continue
            block = AES.new(key, AES.MODE_ECB).encrypt(iv)
            plain = bytes(a ^ b for a, b in zip(block, first))
            length = int.from_bytes(plain[:4], 'little')
            if 0 < length < 1024 and all(32 <= c < 127 for c in plain[4:min(16, 4 + length)]):
                try:
                    decrypt_block(data, enc, key)
                    return off
                except ValueError:
                    continue
    return None


def read_pack(data, key=None):
    """返回 ({路径: bytes}, 信息)。每个文件按目录中的 MD5 校验。"""
    start = locate(data)
    h = header(data, start)
    count = struct.unpack_from('<I', data, h['directory'])[0]
    if h['flags'] & PACK_DIR_ENCRYPTED:
        if key is None:
            raise ValueError('PCK 目录已加密，需要密钥（配置 adapter.key 或 adapter.key_offset，或运行 key 搜索）')
        plain = decrypt_block(data, h['directory'] + 4, key)
    else:
        plain = data[h['directory'] + 4:]
    files, seen, pos = {}, set(), 0
    for _ in range(count):
        length = struct.unpack_from('<I', plain, pos)[0]
        pos += 4
        name = safe_relative(plain[pos:pos + length].rstrip(b'\0').decode('utf-8'))
        pos += length
        offset, size = struct.unpack_from('<QQ', plain, pos)
        digest = plain[pos + 16:pos + 32]
        fflags = struct.unpack_from('<I', plain, pos + 32)[0]
        pos += 36
        if name.casefold() in seen:
            raise ValueError(f'PCK 路径重复: {name}')
        seen.add(name.casefold())
        if fflags & FILE_REMOVAL:
            continue
        absolute = h['base'] + offset
        if fflags & FILE_ENCRYPTED:
            if key is None:
                raise ValueError('资源已加密，需要密钥')
            content = decrypt_block(data, absolute, key)
        else:
            content = data[absolute:absolute + size]
        if len(content) != size or hashlib.md5(content).digest() != digest:
            raise ValueError(f'资源完整性校验失败: {name}')
        files[name] = content
    if h['flags'] & PACK_DIR_ENCRYPTED and pos != len(plain):
        raise ValueError('目录存在未解析数据')
    return files, {'start': start, **h, 'file_count': len(files)}


def build_pack(files, engine=(4, 0, 0)):
    """生成未加密的 PCK v2（相对文件基址），可嵌入任意位置。"""
    entries, seen = [], set()
    for path, content in sorted(files.items()):
        path = safe_relative(path)
        if path.casefold() in seen or not isinstance(content, bytes):
            raise ValueError('路径重复或资源不是 bytes')
        seen.add(path.casefold())
        name = ('res://' + path).encode('utf-8')
        name += bytes((-len(name)) % 4)
        entries.append((name, content))
    head = struct.pack('<4s5IQ', b'GDPC', 2, *engine, PACK_REL_FILEBASE, 0) + bytes(64) + struct.pack('<I', len(entries))
    offset = len(head) + sum(40 + len(n) for n, _ in entries)
    directory, payload = [], []
    for name, content in entries:
        directory.append(struct.pack('<I', len(name)) + name + struct.pack('<QQ', offset, len(content)) + hashlib.md5(content).digest() + struct.pack('<I', 0))
        payload.append(content)
        offset += len(content)
    return head + b''.join(directory) + b''.join(payload)


def embed(original_exe, pack):
    """用新 PCK 替换 EXE 末尾的 pck 节，返回新 EXE 字节（原文件不动）。"""
    sec = pe_section(original_exe)
    if sec is None:
        raise ValueError('EXE 中没有唯一的 pck 节')
    pos, start, size = sec
    if start + size != len(original_exe) and not original_exe[start + size:].rstrip(b'\0') == b'':
        raise ValueError('PCK 不在文件末尾，拒绝截断')
    result = bytearray(original_exe[:start])
    struct.pack_into('<I', result, pos + 16, len(pack))
    return bytes(result) + pack
