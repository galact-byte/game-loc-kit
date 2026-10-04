"""残留原文扫描与打包门禁。"""
import re

from . import catalog, integrity
from .textutil import has_kana, has_source_text
from .validate import check_target

SEGMENT_SPLIT = re.compile(r'[\n\r\t\u3000：:・／/|]+|\[[^\]]*\]|<[^>]*>|\\[A-Za-z]+\[[^\]]*\]')


def residual_scan(texts, mapping, source_lang='ja', allow=()):
    """texts: 画面/截图采集到的文字。返回疑似未翻译的文字列表。

    判据两条：① 仍含假名（日文时）；② 某个片段正好是“已有译文的原文”——能抓住纯汉字日文词。
    allow 为按约定不翻的原文（玩家输入、调试文字等）。
    """
    allow = set(allow)
    known = {s for s in mapping if len(s.strip()) >= 2}
    found = []
    for text in texts:
        if not isinstance(text, str) or not text.strip() or text in allow:
            continue
        pieces = [p.strip() for p in SEGMENT_SPLIT.split(text) if p and p.strip()]
        hit = [p for p in pieces if p in known and p not in allow]
        if hit or (source_lang == 'ja' and has_kana(text) and not any(a in text for a in allow if a)):
            found.append({'text': text, 'untranslated_segments': hit})
    return found


def build_gate(ws, tokens, deep_integrity=False):
    """打包前的硬性检查；返回问题列表，非空即拒绝打包。"""
    problems = []
    st = catalog.status(ws.db)
    if st['usage'].get('pending'):
        problems.append(f'仍有 {st["usage"]["pending"]} 条未做用途审核')
    if st['pending_translation']:
        problems.append(f'仍有 {st["pending_translation"]} 条已放行文字未翻译')
    if st['glossary_conflicts']:
        problems.append(f'词表冲突 {st["glossary_conflicts"]} 处待处理')
    bad = 0
    for row in catalog.all_targets(ws.db):
        if row['target'] is not None and check_target(row['source'], row['target'], tokens):
            bad += 1
    if bad:
        problems.append(f'{bad} 条译文格式校验失败')
    manifest = ws.path('original-manifest.json')
    if not manifest.exists():
        problems.append('缺少原版完整性清单（请先 glk init）')
    else:
        diff = integrity.verify(ws.game_dir, manifest, deep=deep_integrity)
        if diff:
            problems.append(f'原版目录发生变化 {len(diff)} 处，例如: {diff[0]}')
    return problems


def untranslated_source_ratio(mapping, lang='ja'):
    """译文里仍含源语言假名的比例，用于发现“原样提交”。"""
    if not mapping:
        return 0.0
    left = sum(1 for t in mapping.values() if lang == 'ja' and has_kana(t))
    return left / len(mapping)


__all__ = ['residual_scan', 'build_gate', 'untranslated_source_ratio', 'has_source_text']
