"""独立程序应使用随包 CLI，不依赖用户安装 Python。"""
import sys

import pytest

from gamelockit.adapters import get
from gamelockit.cli import render_instructions
from gamelockit.project import Workspace


@pytest.fixture
def workspace(tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    return Workspace.create(tmp_path / '工作 区', game, 'rpgmaker')


def test_frozen_agent_instructions_use_bundled_cli(workspace, tmp_path, monkeypatch):
    bundle = tmp_path / 'Windows 包'
    bundle.mkdir()
    executable = bundle / 'glk.exe'
    executable.touch()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(executable))
    render_instructions(workspace, get('rpgmaker')(workspace))
    for relative in ('work/WORKER_INSTRUCTIONS.md', 'audit/AUDIT_INSTRUCTIONS.md'):
        instructions = workspace.path(relative).read_text(encoding='utf-8')
        assert f'"{executable.as_posix()}" --ws "{workspace.root.as_posix()}"' in instructions
        assert 'python -m gamelockit' not in instructions


def test_frozen_gui_starts_sibling_cli(workspace, tmp_path, monkeypatch):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from gamelockit.gui import ProgressWindow
    from gamelockit import gui
    app = QApplication.instance() or QApplication([])
    bundle = tmp_path / 'Windows 包'
    bundle.mkdir()
    (bundle / 'glk.exe').touch()
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(bundle / 'glk-gui.exe'))
    launched = []
    monkeypatch.setattr(gui.subprocess, 'Popen', lambda args, **kwargs: launched.append((args, kwargs)))
    window = ProgressWindow(workspace.root)
    try:
        window.start_translation()
        assert len(launched) == 1
        args, options = launched[0]
        assert args == [str(bundle / 'glk.exe'), '--ws', str(workspace.root), 'translate']
        assert options['cwd'] == workspace.root
    finally:
        window.close()
        app.processEvents()


def test_incomplete_windows_bundle_reports_missing_cli(workspace, tmp_path, monkeypatch):
    pytest.importorskip('PyQt6')
    from PyQt6.QtWidgets import QApplication
    from gamelockit.gui import ProgressWindow
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'glk-gui.exe'))
    window = ProgressWindow(workspace.root)
    try:
        with pytest.raises(FileNotFoundError, match='glk.exe'):
            window.start_translation()
    finally:
        window.close()
        app.processEvents()
