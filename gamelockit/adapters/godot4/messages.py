"""编译显示层字典：整句精确表 + 带占位符的模板规则（运行时按锚点筛选后用正则匹配）。

别名（aliases）用于游戏在显示前把原文加工成另一种形态的情况，例如把 **强调** 渲染成颜色标签；
这些规则因游戏而异，默认不启用，按工作区配置 adapter.message_aliases 选择。
"""
from collections import Counter
import re

PLACEHOLDER = re.compile(r'\{[^{}\n]+\}|%(?:\d+\$)?[-+0 #]*(?:\d+|\*)?(?:\.(?:\d+|\*))?[sdifxXocv]')


def markup_alias(text):
    # 对应原界面 markup 消费点；颜色和字号捕获自运行时，不能写死主题值。
    index = 0
    def replace(match):
        nonlocal index
        body = next(value for value in match.groups() if value is not None)
        key = '{__zh_style_%d_%%s}' % index
        index += 1
        if match.group(1) is not None:
            return '[color=' + key % 'ink' + ']' + body + '[/color]'
        return ('[bgcolor=' + key % 'bg' + '][color=' + key % 'ink'
                + '][font_size=' + key % 'size' + '] ' + body + ' [/font_size][/color][/bgcolor]')
    return re.sub(r'\*\*(.+?)\*\*|\[\[(.+?)\]\]|\(\((.+?)\)\)', replace, text)


def narration_alias(text):
    if '「' not in text and '“' not in text:
        return text
    return '\n'.join(''.join(part if not part or part.startswith(('「', '“')) else
                            '[color={__zh_narration_color}]' + part + '[/color]'
                            for part in re.split('(「[^」]*」|“[^”]*”)', line))
                     for line in text.split('\n'))


def _narration_pair(source, target):
    alias, target_alias = narration_alias(source), narration_alias(target)
    if '{__zh_narration_color}' in alias and '{__zh_narration_color}' not in target_alias:
        target_alias = '[color={__zh_narration_color}]' + target_alias + '[/color]'
    return alias, target_alias


ALIASES = {
    'double_markup': lambda s, t: (markup_alias(s), markup_alias(t)),
    'quote_narration': _narration_pair,
}


def compile_messages(messages, aliases=()):
    unknown = set(aliases) - set(ALIASES)
    if unknown:
        raise ValueError(f'未知显示别名: {sorted(unknown)}')
    pairs = list(messages.items())
    for source, target in messages.items():
        for name in aliases:
            alias, target_alias = ALIASES[name](source, target)
            if alias != source:
                pairs.append((alias, target_alias))
    # 取较少出现的可见二字片段，避免每句话都尝试数千条共用颜色标签/标点的正则。
    visible_parts = [[part for segment in re.split(r'\[[^\]]*\]', source)
                      for part in PLACEHOLDER.split(segment)] for source, _ in pairs]
    options = [{part[i:i + 2] for part in parts for i in range(len(part) - 1)} for parts in visible_parts]
    frequency = Counter(anchor for choices in options for anchor in choices)
    exact = {}
    rules = []
    anchors = {}
    for pair_index, (source, target) in enumerate(pairs):
        exact[source] = target
        if source == target:
            continue
        matches = list(PLACEHOLDER.finditer(source))
        literals = PLACEHOLDER.split(source)
        if matches:
            literals = [literal.replace('%%', '%') for literal in literals]
        longest = max(visible_parts[pair_index], key=len, default='')
        # 不将单字映射应用到任意单词内部，也不匹配只有变量的表达式。
        if len(longest.strip()) < (1 if matches else 3):
            continue
        whole_only = bool(matches) and len(longest.strip()) == 1
        anchor = min(options[pair_index], key=lambda part: (frequency[part], part)) if options[pair_index] else longest.strip()[:2]
        pattern = ''
        groups = {}
        occurrences = Counter()
        group_count = 0
        pos = 0
        for match in matches:
            token = match.group()
            pattern += re.escape(source[pos:match.start()].replace('%%', '%'))
            # 原游戏在发言者处保留全名、叙述处缩写同一个{name}；显示值不再相等。
            key = (token, 0 if token.startswith('{') and token != '{name}' else occurrences[token])
            occurrences[token] += 1
            if key in groups:
                pattern += rf'\g<{groups[key]}>'
            else:
                group_count += 1
                groups[key] = group_count
                numeric = token.startswith('%') and token[-1] in 'difxX'
                if numeric:
                    pattern += r'( *[-+0-9.,eExXa-fA-F]+ *)'
                elif match.start() == 0:
                    # 开头没有固定锚点，不能吞掉前一字段或列表项。
                    style = r'\[/?(?:color|bgcolor|font_size|b|i|u)(?:=[^\]\n]+)?\]'
                    pattern += rf'((?:{style}|[^\n：:・\[\]])*?)'
                else:
                    pattern += r'([^\n]*?)'
            pos = match.end()
        pattern += re.escape(source[pos:].replace('%%', '%') if matches else source[pos:])
        if matches and matches[-1].end() == len(source):
            pattern += r'(?=\n|$)'
        if whole_only:
            pattern = '^' + pattern + '$'
        # Python 与 PCRE 均支持编号反向引用。
        pattern = re.sub(r'\\g<(\d+)>', lambda m: '\\' + m[1], pattern)
        parts = []
        occurrences.clear()
        pos = 0
        for match in PLACEHOLDER.finditer(target):
            token = match.group()
            key = (token, 0 if token.startswith('{') and token != '{name}' else occurrences[token])
            occurrences[token] += 1
            parts.extend([target[pos:match.start()].replace('%%', '%'), groups[key]])
            pos = match.end()
        parts.append(target[pos:].replace('%%', '%') if matches else target[pos:])
        index = len(rules)
        rules.append({'pattern': pattern, 'parts': parts, 'specificity': sum(len(literal) for literal in literals)})
        anchors.setdefault(anchor, []).append(index)
    return {'exact': exact, 'rules': rules, 'anchors': anchors}
