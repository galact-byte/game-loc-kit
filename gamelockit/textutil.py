"""与引擎无关的文本判定工具。"""
import re

KANA = re.compile(r'[\u3040-\u309f\u30a0-\u30ff\uff66-\uff9f]')
CJK = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')
HANGUL = re.compile(r'[\uac00-\ud7af]')
LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
PATHLIKE = re.compile(r'^(res|user|uid|https?|file)://|^[\w./\\-]+\.(png|jpg|ogg|wav|mp3|json|tscn|tres|gd|gdc|js|png|webp|ks|tjs|txt|csv|asset|prefab)$', re.I)
IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_.:/-]*$')

SOURCE_DETECTORS = {
    'ja': lambda s: bool(KANA.search(s) or CJK.search(s)),
    'en': lambda s: bool(LATIN_WORD.search(s)),
    'ko': lambda s: bool(HANGUL.search(s)),
    'zh': lambda s: bool(CJK.search(s)),
}


def has_source_text(text, lang='ja'):
    """原文语言是否可能出现在 text 中；日文同时计入纯汉字词，避免只查假名的漏检。"""
    detector = SOURCE_DETECTORS.get(lang)
    if detector is None:
        raise ValueError(f'不支持的源语言: {lang}')
    return detector(text)


def is_candidate(text, lang='ja'):
    """可作为翻译候选的字符串：含源语言文字，且不是路径或纯标识符。"""
    if not isinstance(text, str) or not text.strip():
        return False
    stripped = text.strip()
    if PATHLIKE.search(stripped):
        return False
    if lang == 'en' and IDENTIFIER.match(stripped):
        return False
    return has_source_text(stripped, lang)


def has_kana(text):
    return bool(KANA.search(text))
