"""最小修改导出项目配置 project.binary（ECFG）；其他设置的 Variant 字节保持原样。"""
import struct


def string_variant(text):
    data = text.encode('utf-8')
    return struct.pack('<II', 4, len(data)) + data + bytes((-len(data)) % 4)


def patch_settings(data, changes):
    if data[:4] != b'ECFG' or len(data) < 8:
        raise ValueError('无效项目配置')
    count = struct.unpack_from('<I', data, 4)[0]
    position = 8
    values = dict(changes)
    try:
        for _ in range(count):
            size = struct.unpack_from('<I', data, position)[0]
            position += 4
            key = data[position:position + size].decode('utf-8')
            position += size
            size = struct.unpack_from('<I', data, position)[0]
            position += 4
            value = data[position:position + size]
            if len(value) != size:
                raise ValueError('配置值截断')
            position += size
            if key not in changes:
                if key in values:
                    raise ValueError('配置键重复')
                values[key] = value
    except (struct.error, UnicodeDecodeError) as error:
        raise ValueError('配置截断或格式无效') from error
    if position != len(data):
        raise ValueError('配置含尾随字节')
    result = b'ECFG' + struct.pack('<I', len(values))
    for key, value in values.items():
        key = key.encode('utf-8')
        result += struct.pack('<I', len(key)) + key + struct.pack('<I', len(value)) + value
    return result


def bool_variant(value):
    return struct.pack('<II', 1, int(bool(value)))


def read_string(data, key):
    """读取 ECFG 中某个字符串设置；不存在或不是字符串返回 None。"""
    if data[:4] != b'ECFG':
        return None
    count = struct.unpack_from('<I', data, 4)[0]
    pos = 8
    for _ in range(count):
        size = struct.unpack_from('<I', data, pos)[0]
        name = data[pos + 4:pos + 4 + size].decode('utf-8', 'replace')
        pos += 4 + size
        size = struct.unpack_from('<I', data, pos)[0]
        value = data[pos + 4:pos + 4 + size]
        pos += 4 + size
        if name == key and len(value) >= 8 and struct.unpack_from('<I', value)[0] == 4:
            length = struct.unpack_from('<I', value, 4)[0]
            return value[8:8 + length].decode('utf-8', 'replace')
    return None
