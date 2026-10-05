"""合成的 RPG Maker MV 小游戏走完整流程：init → extract → 审核/导入译文 → 门禁 → build。"""
import json

from gamelockit.cli import main


def _game(root):
    data = root / 'www' / 'data'
    data.mkdir(parents=True)
    (root / 'www' / 'js').mkdir()
    (root / 'www' / 'js' / 'rpg_core.js').write_text('//')
    (root / 'www' / 'js' / 'main.js').write_text('if ($gameActors.actor(1).name() === "勇者") {}', encoding='utf-8')
    (root / 'www' / 'save').mkdir()
    (root / 'www' / 'save' / 'file1.rpgsave').write_text('personal')
    (data / 'System.json').write_text(json.dumps({'gameTitle': 'テスト', 'terms': {}}), encoding='utf-8')
    (data / 'Actors.json').write_text(json.dumps([None, {'name': '勇者', 'profile': '旅人です'}]), encoding='utf-8')
    page = {'list': [{'code': 401, 'parameters': ['\\C[2]こんにちは']}, {'code': 0, 'parameters': []}]}
    (data / 'Map001.json').write_text(json.dumps({'displayName': '', 'events': [None, {'pages': [page]}]}), encoding='utf-8')


def _run(capsys, *argv):
    code = main(list(argv))
    return code, json.loads(capsys.readouterr().out)


def test_pipeline_gate_and_build(tmp_path, capsys):
    game, ws = tmp_path / 'game', str(tmp_path / 'ws')
    _game(game)
    assert _run(capsys, '--ws', ws, 'init', str(game))[1]['engine'] == 'rpgmaker'
    code, ext = _run(capsys, '--ws', ws, 'extract')
    assert ext['usage'] == {'display': 3, 'pending': 1}  # 被脚本按名字比较的角色名待审

    code, built = _run(capsys, '--ws', ws, 'build', '--out', str(tmp_path / 'out0'), '--no-probe')
    assert code == 1 and not built['ok'] and built['problems']

    rows = [{'source': '勇者', 'usage': 'dual', 'reason': '脚本比较'},
            {'source': 'テスト', 'target': '测试'}, {'source': '旅人です', 'target': '是旅人'},
            {'source': '\\C[2]こんにちは', 'target': '你好'}]  # 丢了控制符，必须被拒
    (tmp_path / 'imp.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    _, imp = _run(capsys, '--ws', ws, 'import', str(tmp_path / 'imp.json'))
    assert imp['targets_applied'] == 2 and imp['rejected'] == 1

    rows = [{'source': '\\C[2]こんにちは', 'target': '\\C[2]你好'}]
    (tmp_path / 'imp.json').write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    _run(capsys, '--ws', ws, 'import', str(tmp_path / 'imp.json'))
    out = tmp_path / 'out'
    code, built = _run(capsys, '--ws', ws, 'build', '--out', str(out), '--no-probe')
    assert code == 0 and built['ok'] and built['original_changes'] == []

    actors = json.loads((out / 'www/data/Actors.json').read_text(encoding='utf-8'))
    assert actors[1] == {'name': '勇者', 'profile': '是旅人'}  # dual 不放行
    assert '\\\\C[2]你好' in (out / 'www/data/Map001.json').read_text(encoding='utf-8')
    assert not (out / 'www/save/file1.rpgsave').exists()  # 玩家存档不进副本
    assert json.loads((game / 'www/data/Actors.json').read_text(encoding='utf-8'))[1]['profile'] == '旅人です'


def test_init_locale_option_written(tmp_path, capsys):
    """光盘镜像等生肉本体需要日文环境，与引擎无关：init 时可直接声明转区启动。"""
    game, ws = tmp_path / 'game', tmp_path / 'ws'
    _game(game)
    _run(capsys, '--ws', str(ws), 'init', str(game), '--locale', 'ja')
    assert json.loads((ws / 'glk.json').read_text(encoding='utf-8'))['launch']['locale'] == 'ja'


def test_kirikiri_codepage_detected_per_game(tmp_path):
    """吉里吉里本身不要求转区；只有脚本按系统代码页（无 BOM 的 Shift-JIS）存储时才需要。"""
    from gamelockit.adapters.kirikiri import KirikiriAdapter
    from gamelockit.formats import xp3
    from gamelockit.project import Workspace
    results = {}
    for label, raw in (('unicode', b'\xff\xfe' + 'テスト\n'.encode('utf-16le')), ('sjis', 'テスト\n'.encode('cp932'))):
        game = tmp_path / label
        game.mkdir()
        xp3.write(game / 'data.xp3', {'startup.tjs': b'\xff\xfe' + 'var a=1;'.encode('utf-16le'), 'scenario/first.ks': raw})
        results[label] = KirikiriAdapter(Workspace.create(tmp_path / f'ws-{label}', game, 'kirikiri')).legacy_codepage
    assert results == {'unicode': False, 'sjis': True}


def test_piped_output_is_utf8():
    """Agent 通过管道读取输出；不能随系统代码页（如 GBK）编码，否则中文乱码。"""
    import os
    import subprocess
    import sys
    env = {k: v for k, v in os.environ.items() if not k.startswith('PYTHONIO') and k != 'PYTHONUTF8'}
    out = subprocess.run([sys.executable, '-m', 'gamelockit', '--help'], capture_output=True, env=env)
    assert '多引擎游戏汉化工作流' in out.stdout.decode('utf-8')
    err = subprocess.run([sys.executable, '-m', 'gamelockit', 'status'], capture_output=True, env=env)
    assert '需要 --ws 工作区目录' in err.stderr.decode('utf-8')
