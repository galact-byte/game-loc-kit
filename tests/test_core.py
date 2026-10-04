"""与引擎无关的核心规则：候选判定、用途审核放行、译文格式校验、残留扫描、原版完整性。"""
import pytest

from gamelockit import catalog, integrity, quality
from gamelockit.adapters.base import Occurrence
from gamelockit.textutil import is_candidate
from gamelockit.validate import check_target, compile_tokens


def test_candidate_includes_kanji_only_japanese_and_skips_paths():
    assert is_candidate('恋人')  # 纯汉字日文词也要提取
    assert is_candidate('こんにちは')
    assert not is_candidate('img/face01.png')
    assert not is_candidate('res://scenes/main.tscn')
    assert not is_candidate('   ')
    assert is_candidate('Start Game', 'en') and not is_candidate('player_hp', 'en')


def _occ(text, hint):
    return Occurrence(text, 'test', 'ref', '', hint)


def test_only_display_is_released_and_audit_requires_reason(tmp_path):
    db = tmp_path / 'c.sqlite3'
    catalog.add_occurrences(db, [_occ('はい', 'display'), _occ('フラグ', 'protected'), _occ('名前', 'unknown')], False)
    st = catalog.status(db)
    assert st['usage'] == {'display': 1, 'protected': 1, 'pending': 1}
    assert st['released'] == 1
    pending = catalog.pending_audit(db)
    assert [p['source'] for p in pending] == ['名前']
    with pytest.raises(ValueError):
        catalog.apply_usage(db, [{'id': pending[0]['id'], 'usage': 'display', 'reason': ' '}], False)
    catalog.apply_usage(db, [{'id': pending[0]['id'], 'usage': 'dual', 'reason': '脚本按名字查找'}], False)
    assert catalog.status(db)['released'] == 1  # 直接替换型引擎不放行 dual


def test_reextract_keeps_existing_audit(tmp_path):
    db = tmp_path / 'c.sqlite3'
    catalog.add_occurrences(db, [_occ('名前', 'unknown')], False)
    iid = catalog.pending_audit(db)[0]['id']
    catalog.apply_usage(db, [{'id': iid, 'usage': 'protected', 'reason': '比较用'}], False)
    assert catalog.add_occurrences(db, [_occ('名前', 'display')], False) == 0
    assert catalog.status(db)['usage'] == {'protected': 1}


@pytest.mark.parametrize('target,error', [
    ('你好{name}', None),
    ('你好', '占位符或标记不匹配'),
    ('你好\n{name}', '换行数量不匹配'),
    (' 你好{name}', '首尾空白不一致'),
    ('', '译文为空'),
])
def test_check_target(target, error):
    errors = check_target('こんにちは{name}', target, compile_tokens())
    assert (error in errors) if error else errors == []


def test_engine_tokens_are_protected():
    tokens = compile_tokens((r'\\[A-Za-z]+\[[^\]\n]*\]',))
    assert check_target(r'\c[2]はい', r'\c[2]是', tokens) == []
    assert check_target(r'\c[2]はい', '是', tokens)


def test_residual_scan_catches_kana_and_known_kanji_source():
    mapping = {'恋人': '恋人关系', '開始': '开始'}
    found = quality.residual_scan(['开始', '恋人', 'ここは', '已翻译文字'], mapping)
    assert [f['text'] for f in found] == ['恋人', 'ここは']
    assert quality.residual_scan(['ここは'], mapping, allow=['ここは']) == []


def test_integrity_detects_original_change(tmp_path):
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'a.dat').write_bytes(b'abc')
    manifest = tmp_path / 'm.json'
    integrity.record(game, manifest)
    assert not integrity.verify(game, manifest, deep=True)
    (game / 'a.dat').write_bytes(b'abd')
    assert integrity.verify(game, manifest, deep=True)
