"""原版完整性清单：初始化时记录，构建/发布前核对，证明原版文件未被改动。

工具从不写入原版目录（汉化副本输出到别处），因此不复制整份游戏做备份；
清单用于发现任何意外改动。
"""
import fnmatch
import hashlib
from pathlib import Path

from .project import read_json, write_json


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _files(root, exclude):
    for path in sorted(Path(root).rglob('*')):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if not any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(path.name, g) for g in exclude):
                yield rel, path


def record(game_dir, manifest_path, exclude=()):
    entries = {}
    for rel, path in _files(game_dir, exclude):
        st = path.stat()
        entries[rel] = {'size': st.st_size, 'mtime_ns': st.st_mtime_ns, 'sha256': sha256(path)}
    write_json(manifest_path, {'game_dir': str(game_dir), 'exclude': list(exclude), 'files': entries})
    return len(entries)


def verify(game_dir, manifest_path, deep=False):
    """返回差异列表；deep=True 时重新计算全部哈希。"""
    manifest = read_json(manifest_path)
    expected = manifest['files']
    actual = dict(_files(game_dir, manifest.get('exclude', ())))
    problems = [f'缺失: {rel}' for rel in expected if rel not in actual]
    problems += [f'新增: {rel}' for rel in actual if rel not in expected]
    for rel, info in expected.items():
        path = actual.get(rel)
        if path is None:
            continue
        st = path.stat()
        if st.st_size != info['size']:
            problems.append(f'大小变化: {rel}')
        elif (deep or st.st_mtime_ns != info['mtime_ns']) and sha256(path) != info['sha256']:
            problems.append(f'内容变化: {rel}')
    return problems
