"""Windows 独立程序入口；两个 EXE 共用打包后的依赖。"""
from pathlib import Path
import sys

if Path(sys.executable).stem.lower() == 'glk-gui':
    from gamelockit.gui import main
else:
    from gamelockit.cli import main

raise SystemExit(main())
