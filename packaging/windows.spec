# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import importlib.metadata
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'packaging/windows_entry.py')],
    pathex=[str(root)],
    datas=collect_data_files('gamelockit') + collect_data_files('UnityPy'),
    hiddenimports=collect_submodules('gamelockit.adapters') + collect_submodules('UnityPy'),
    excludes=['PyQt5', 'PySide2', 'PySide6', 'PyQt6.QtPdf', 'PyQt6.QtPdfWidgets',
              'tkinter', 'matplotlib', 'scipy', 'IPython', 'pytest'],
)
# QWidget 窗口不使用 PDF 图像插件或 Mesa 软件 OpenGL。
analysis.binaries = [item for item in analysis.binaries
                     if Path(item[0]).name.lower() not in {'opengl32sw.dll', 'qt6pdf.dll', 'qpdf.dll'}]
# 按实际收集的模块补齐依赖元数据，其中包含原始版权和许可文件。
providers = importlib.metadata.packages_distributions()
distributions = {'PyInstaller', 'PyQt6-Qt6'}
for module, *_ in analysis.pure:
    distributions.update(providers.get(module.split('.')[0], []))
for module, *_ in analysis.binaries:
    distributions.update(providers.get(Path(module).parts[0].split('.')[0], []))
metadata = set()
for name in sorted(distributions):
    for source, destination in copy_metadata(name, recursive=True):
        if destination not in metadata:
            analysis.datas += Tree(source, prefix=destination)
            metadata.add(destination)
pyz = PYZ(analysis.pure)
cli = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='glk', console=True, upx=False)
gui = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name='glk-gui', console=False, upx=False)
COLLECT(cli, gui, analysis.binaries, analysis.datas, name='game-loc-kit', upx=False)
