"""Electron asar 归档读写（不依赖 node）。"""
import hashlib
import json
from pathlib import PurePosixPath
import struct

BLOCK = 4 * 1024 * 1024


def _header(data):
    size = struct.unpack_from('<I', data, 4)[0]
    json_len = struct.unpack_from('<I', data, 12)[0]
    header = json.loads(data[16:16 + json_len].decode('utf-8'))
    return header, 8 + size


def read(data, unpacked_dir=None):
    """返回 {相对路径: bytes}；标记为 unpacked 的文件从 unpacked_dir 读取（缺失则跳过）。"""
    header, base = _header(data)
    files = {}

    def walk(node, prefix):
        for name, entry in node.get('files', {}).items():
            path = f'{prefix}{name}'
            if 'files' in entry:
                walk(entry, path + '/')
            elif 'link' in entry:
                continue
            elif entry.get('unpacked'):
                if unpacked_dir is not None:
                    target = unpacked_dir / path
                    if target.is_file():
                        files[path] = target.read_bytes()
            else:
                offset = base + int(entry['offset'])
                files[path] = data[offset:offset + int(entry['size'])]
    walk(header, '')
    return files


def _integrity(content):
    blocks = [hashlib.sha256(content[i:i + BLOCK]).hexdigest() for i in range(0, max(len(content), 1), BLOCK)]
    return {'algorithm': 'SHA256', 'hash': hashlib.sha256(content).hexdigest(), 'blockSize': BLOCK, 'blocks': blocks}


def rewrite(data, replacements):
    """在原归档结构上替换若干文件内容，返回新归档字节。只允许替换已存在的打包文件。"""
    header, base = _header(data)
    payload = []
    offset = 0
    seen = set()

    def walk(node, prefix):
        nonlocal offset
        for name, entry in node.get('files', {}).items():
            path = f'{prefix}{name}'
            if 'files' in entry:
                walk(entry, path + '/')
            elif 'link' in entry or entry.get('unpacked'):
                if path in replacements:
                    raise ValueError(f'不能替换未打包的文件: {path}')
            else:
                old = base + int(entry['offset'])
                content = replacements[path] if path in replacements else data[old:old + int(entry['size'])]
                seen.add(path)
                entry['offset'] = str(offset)
                entry['size'] = len(content)
                if 'integrity' in entry:
                    entry['integrity'] = _integrity(content)
                payload.append(content)
                offset += len(content)
    walk(header, '')
    missing = set(replacements) - seen
    if missing:
        raise ValueError(f'归档中不存在: {sorted(missing)[:3]}')
    raw = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    padded = raw + bytes((-len(raw)) % 4)
    pickle = struct.pack('<II', len(padded) + 4, len(raw)) + padded
    return struct.pack('<II', 4, len(pickle)) + pickle + b''.join(payload)


def safe(path):
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError(f'不安全路径: {path}')
    return path
