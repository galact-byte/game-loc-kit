"""译文格式校验：占位符、标记、控制字符、首尾空白必须与原文一致。

各引擎的标记语法由适配器通过 token_patterns 提供，这里只放通用规则。
"""
from collections import Counter
import re

GENERIC_PATTERNS = (
    r'\{[^{}\n]*\}',                                                          # {name} / {0}
    r'%(?:\d+\$)?[-+0 #]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[sdifxXocv]',           # printf
)


def compile_tokens(extra=()):
    return re.compile('|'.join(f'(?:{p})' for p in (*extra, *GENERIC_PATTERNS)))


def edge_space(text):
    return len(text) - len(text.lstrip()), len(text) - len(text.rstrip())


def check_target(source, target, tokens):
    """返回错误列表；空列表表示通过。tokens 为 compile_tokens 的结果。"""
    errors = []
    if not isinstance(target, str) or not target.strip():
        return ['译文为空']
    if '\x00' in target:
        errors.append('译文含 NUL')
    if Counter(tokens.findall(source)) != Counter(tokens.findall(target)):
        errors.append('占位符或标记不匹配')
    for control, name in (('\n', '换行'), ('\t', '制表符'), ('\r', '回车')):
        if source.count(control) != target.count(control):
            errors.append(f'{name}数量不匹配')
    # 拼接片段依赖前后空白，宽度不同的全角/半角空格都必须保留。
    if (edge_space(source)[0] > 0) != (edge_space(target)[0] > 0) or (edge_space(source)[1] > 0) != (edge_space(target)[1] > 0):
        errors.append('首尾空白不一致')
    return errors
