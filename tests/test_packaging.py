"""发布依赖源码时只复制安全路径下的许可文本。"""
import io
from pathlib import Path
import runpy
import tarfile

import pytest


@pytest.fixture
def packaging_helpers():
    return runpy.run_path(str(Path(__file__).resolve().parents[1] / 'packaging/prepare_windows.py'))


def archive_with_file(path, name, content=b'License notice'):
    with tarfile.open(path, 'w') as archive:
        entry = tarfile.TarInfo(name)
        entry.size = len(content)
        archive.addfile(entry, io.BytesIO(content))


def test_notices_reject_absolute_posix_paths_on_windows(tmp_path, monkeypatch, packaging_helpers):
    archive = tmp_path / 'source.tar'
    archive_with_file(archive, '/escape/LICENSE')
    writes = []
    monkeypatch.setattr(Path, 'mkdir', lambda *args, **kwargs: None)
    monkeypatch.setattr(Path, 'write_bytes', lambda self, content: writes.append(self))
    with pytest.raises(ValueError, match='不安全'):
        packaging_helpers['copy_notices'](archive, tmp_path / 'notices')
    assert writes == []


def test_spdx_license_directory_is_preserved(tmp_path, packaging_helpers):
    archive = tmp_path / 'source.tar'
    archive_with_file(archive, 'qtbase/LICENSES/FTL.txt')
    output = tmp_path / 'notices'
    packaging_helpers['copy_notices'](archive, output)
    assert (output / 'qtbase/LICENSES/FTL.txt').read_bytes() == b'License notice'
