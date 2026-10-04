"""开发自测：给已放行条目填入“伪译文”（标记外的假名换成“中”），用于端到端构建与画面检查。

只写入测试工作区；伪译文不能发布（配合 glk build --force-draft 使用）。
用法: python tests/pseudo_translate.py <工作区>
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gamelockit import catalog  # noqa: E402
from gamelockit.adapters import get  # noqa: E402
from gamelockit.project import Workspace  # noqa: E402
from gamelockit.validate import check_target, compile_tokens  # noqa: E402

KANA = re.compile(r'[\u3041-\u3096\u30a1-\u30fa]')


def pseudo(source, tokens):
    parts, last = [], 0
    for m in tokens.finditer(source):
        parts.append(KANA.sub('中', source[last:m.start()]))
        parts.append(m.group(0))
        last = m.end()
    parts.append(KANA.sub('中', source[last:]))
    result = ''.join(parts)
    # 纯汉字条目没有假名可换，前缀“中”让画面上能区分“已替换”与“漏翻”
    return result if result != source else '中' + source


def main(ws_dir):
    ws = Workspace(ws_dir)
    tokens = compile_tokens(get(ws.engine).token_patterns)
    done = bad = 0
    with catalog.connection(ws.db) as con:
        for row in con.execute('SELECT id, source FROM items WHERE released=1 AND target IS NULL').fetchall():
            target = pseudo(row['source'], tokens)
            if check_target(row['source'], target, tokens):
                bad += 1
                continue
            con.execute('UPDATE items SET target=? WHERE id=?', (target, row['id']))
            done += 1
    print({'filled': done, 'skipped_invalid': bad})


if __name__ == '__main__':
    main(sys.argv[1])
