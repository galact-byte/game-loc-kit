"""共用存档保护：启动期间被改动/新建/删除的内容在退出后必须原样还原。"""
from gamelockit import saveguard


def test_dir_restored_after_changes(tmp_path):
    saves, fresh = tmp_path / 'saves', tmp_path / 'fresh'
    saves.mkdir()
    (saves / 'slot1').write_text('player progress')
    with saveguard.guard([('dir', saves), ('dir', fresh)], tmp_path / 'bak'):
        (saves / 'slot1').write_text('overwritten by test run')
        (saves / 'config').write_text('new')
        fresh.mkdir()
        (fresh / 'x').write_text('created')
    assert [p.name for p in saves.iterdir()] == ['slot1']
    assert (saves / 'slot1').read_text() == 'player progress'
    assert not fresh.exists()


def test_restored_even_when_run_fails(tmp_path):
    saves = tmp_path / 'saves'
    saves.mkdir()
    (saves / 'slot1').write_text('a')
    try:
        with saveguard.guard([('dir', saves)], tmp_path / 'bak'):
            (saves / 'slot1').unlink()
            raise KeyError('crash')
    except KeyError:
        pass
    assert (saves / 'slot1').read_text() == 'a'


def test_waits_for_locked_file(tmp_path, monkeypatch):
    saves = tmp_path / 'saves'
    saves.mkdir()
    (saves / 'Player.log').write_text('old')
    real_copy, calls = saveguard.shutil.copy2, []

    def flaky(src, dst):
        calls.append(dst)
        if len(calls) == 1:
            raise PermissionError('in use')
        return real_copy(src, dst)
    monkeypatch.setattr(saveguard.shutil, 'copy2', flaky)
    monkeypatch.setattr(saveguard.time, 'sleep', lambda s: None)
    with saveguard.guard([('dir', saves)], tmp_path / 'bak'):
        (saves / 'Player.log').write_text('new')
    assert (saves / 'Player.log').read_text() == 'old' and len(calls) == 2
