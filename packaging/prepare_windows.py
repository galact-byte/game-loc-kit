"""为 Windows 包整理许可、对应源码和重建说明。"""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile


def download(url, destination, expected=None):
    for attempt in range(3):
        try:
            digest = hashlib.sha256()
            with urllib.request.urlopen(url, timeout=60) as response, destination.open('wb') as target:
                while block := response.read(1024 * 1024):
                    target.write(block)
                    digest.update(block)
            checksum = digest.hexdigest()
            if expected and checksum != expected:
                raise ValueError(f'源码校验失败：{destination.name}')
            return checksum
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def copy_notices(archive, destination):
    """仅复制许可文本；不解包任意路径或执行归档中的文件。"""
    def save(name, data):
        relative = PurePosixPath(name.replace('\\', '/'))
        if relative.is_absolute() or '..' in relative.parts or ':' in relative.parts[0]:
            raise ValueError(f'不安全的源码归档路径：{name}')
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def is_notice(name, size):
        path = PurePosixPath(name.replace('\\', '/'))
        return size < 2 * 1024 * 1024 and (
            any(word in path.name.lower() for word in ('license', 'copying', 'notice'))
            or any(part.lower() == 'licenses' for part in path.parts)
            or path.name == 'qt_attribution.json'
        )

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                if not entry.is_dir() and is_notice(entry.filename, entry.file_size):
                    save(entry.filename, source.read(entry))
    else:
        with tarfile.open(archive) as source:
            for entry in source:
                if entry.isfile() and is_notice(entry.name, entry.size):
                    save(entry.name, source.extractfile(entry).read())


def prepare(bundle, output):
    root = Path(__file__).resolve().parent.parent
    version = importlib.metadata.version('game-loc-kit')
    tag = 'v' + version
    release = f'https://github.com/galact-byte/game-loc-kit/releases/tag/{tag}'
    source_name = f'game-loc-kit-{version}-dependency-sources.zip'
    licenses = bundle / 'licenses'
    licenses.mkdir(exist_ok=True)
    for name in ('LICENSE', 'NOTICE', 'README.md'):
        shutil.copy2(root / name, bundle / name)
    shutil.copy2(root / 'licenses/LEGACY-MIT.txt', licenses)
    shutil.copy2(Path(sys.base_prefix) / 'LICENSE.txt', licenses / 'PYTHON-LICENSE.txt')
    qt_version = importlib.metadata.version('PyQt6-Qt6')
    qt_bin = bundle / '_internal/PyQt6/Qt6/bin'
    assert {p.name for p in qt_bin.glob('Qt6*.dll')} <= {'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll', 'Qt6Network.dll', 'Qt6Svg.dll'}
    distributions = sorted((d for d in importlib.metadata.distributions(path=[str(bundle / '_internal')])
                            if d.metadata['Name'].lower().replace('_', '-') != 'game-loc-kit'), key=lambda d: d.metadata['Name'].lower())
    assert {'pyqt6', 'pyqt6-sip', 'unitypy', 'pycryptodome'} <= {d.metadata['Name'].lower().replace('_', '-') for d in distributions}
    records = []
    with tempfile.TemporaryDirectory(prefix='glk-sources-', dir=output.parent) as folder:
        staging = Path(folder)

        def collect(name, package_version, url, expected=None):
            archive = staging / url.rsplit('/', 1)[-1]
            print(f'Source: {name} {package_version}', flush=True)
            checksum = download(url, archive, expected)
            copy_notices(archive, licenses / name)
            records.append({'name': name, 'version': package_version, 'url': url, 'sha256': checksum, 'archive': archive.name})

        for dist in distributions:
            name = dist.metadata['Name']
            if name.lower().replace('_', '-') == 'pyqt6-qt6':
                continue
            with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{dist.version}/json', timeout=60) as response:
                metadata = json.load(response)
            source = next((item for item in metadata['urls'] if item['packagetype'] == 'sdist'), None)
            if source is None:
                raise RuntimeError(f'缺少对应源码包：{name} {dist.version}')
            collect(name, dist.version, source['url'], source['digests']['sha256'])
        for module in ('qtbase', 'qtimageformats', 'qtsvg'):
            series = '.'.join(qt_version.split('.')[:2])
            collect(module, qt_version,
                    f'https://download.qt.io/official_releases/qt/{series}/{qt_version}/submodules/{module}-everywhere-src-{qt_version}.tar.xz')
        python_version = '.'.join(map(str, sys.version_info[:3]))
        collect('Python', python_version, f'https://www.python.org/ftp/python/{python_version}/Python-{python_version}.tar.xz')
        (staging / 'sources.json').write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
        requirements = '\n'.join(f"{d.metadata['Name']}=={d.version}" for d in distributions) + '\n'
        (bundle / 'BUILD-REQUIREMENTS.txt').write_text(requirements, encoding='utf-8')
        (staging / 'BUILD-REQUIREMENTS.txt').write_text(requirements, encoding='utf-8')
        notes = f'''# 对应源码与重新构建

本软件使用 GPLv3，详见 LICENSE；第三方部分分别遵守 licenses/ 与 _internal/*.dist-info/ 中的原始许可。

- 项目源码和构建脚本：本版本 Release 的 game_loc_kit-{version}.tar.gz，或 https://github.com/galact-byte/game-loc-kit/tree/{tag} 。
- 对应第三方源码：同一 Release 的 {source_name}，其中 sources.json 记录实际版本、原始下载链接和 SHA-256。
- 下载页面：{release} 。第三方源码归档也可按下表从原始来源获取。

Windows 独立包未修改 Python、PyQt6 或 Qt 的源码，使用 PyPI 官方二进制 wheel 和 PyInstaller 引导程序。
使用单目录动态链接布局，Qt DLL 在 _internal/PyQt6/Qt6/bin；可以用兼容的修改版替换，无签名或启动校验限制。
在许可允许的范围内，可为调试此类修改而逆向分析。MSVC 等系统运行库由其各自许可证管辖。

重新构建项目（Windows x64、Python {python_version}）：解压项目源码包，在其根目录依次运行：

```powershell
python -m pip install -r packaging/windows-requirements.txt
python -m pip install ".[all,gui]"
python -m PyInstaller --noconfirm --clean --distpath dist --workpath build packaging/windows.spec
python packaging/prepare_windows.py --bundle dist/game-loc-kit --output dist
```

BUILD-REQUIREMENTS.txt 记录此次收集的依赖精确版本；Qt/PyQt、Python 和其他依赖的源码归档中各自包含其构建说明。
PyQt6 的构建入口为 pyproject.toml（SIP 构建后端），Qt 模块使用各自 CMakeLists.txt，Python 见 PCbuild/readme.txt。
从源码构建第三方组件可能还需要对应的编译器、SDK 与开发工具，不包含在面向用户的 Windows 运行包中。

| 组件 | 版本 | 上游对应源码 |
|---|---|---|
'''
        notes += ''.join(f"| {r['name']} | {r['version']} | {r['url']} |\n" for r in records)
        (bundle / 'SOURCE_CODE.md').write_text(notes, encoding='utf-8')
        (staging / 'SOURCE_CODE.md').write_text(notes, encoding='utf-8')
        shutil.copy2(root / 'LICENSE', staging / 'LICENSE')
        with zipfile.ZipFile(output / source_name, 'w', compression=zipfile.ZIP_STORED) as target:
            for path in sorted(staging.iterdir()):
                target.write(path, path.name)
    print(f'Prepared licenses and {len(records)} corresponding source archives', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    prepare(args.bundle.resolve(), args.output.resolve())
