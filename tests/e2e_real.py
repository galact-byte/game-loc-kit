"""开发自测：对一款真实游戏跑 init → extract → 伪译 → 草稿构建 → 截图 OCR，最后核对原版未变。

待审条目一律按“保护”处理（只验证流程，不代表审核结论）；伪译文不能发布。
用法: python tests/e2e_real.py <游戏目录> <工作区> [--wait 秒] [--keep-build]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gamelockit import catalog, integrity  # noqa: E402
from gamelockit.project import Workspace  # noqa: E402


def glk(ws, *argv):
    cmd = [sys.executable, '-m', 'gamelockit', '--ws', str(ws), *argv]
    env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    done = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env)
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = {'raw': done.stdout[-1500:], 'stderr': done.stderr[-1500:]}
    return done.returncode, data


def main():
    p = argparse.ArgumentParser()
    p.add_argument('game'); p.add_argument('ws')
    p.add_argument('--wait', type=int, default=15)
    p.add_argument('--source-lang', default='ja')
    p.add_argument('--step', action='append', default=[])
    p.add_argument('--keep-build', action='store_true')
    # 显示层引擎（Godot/Unity）内部原值不变，自测时可把待审核条目当显示文字放行，以覆盖全量渲染
    p.add_argument('--pending-as', choices=('protected', 'display'), default='protected')
    a = p.parse_args()
    ws = Path(a.ws)
    report = {}
    if not (ws / 'glk.json').exists():
        report['init'] = glk(ws, 'init', a.game, '--source-lang', a.source_lang)[1]
    report['extract'] = glk(ws, 'extract')[1]
    w = Workspace(ws)
    with catalog.connection(w.db) as con:
        pending = [r['id'] for r in con.execute("SELECT id FROM items WHERE usage='pending'")]
    if pending:
        catalog.apply_usage(w.db, [{'id': i, 'usage': a.pending_as, 'reason': 'e2e 自测'} for i in pending], False)
    filled = subprocess.run([sys.executable, str(ROOT / 'tests' / 'pseudo_translate.py'), str(ws)], capture_output=True, text=True, encoding='utf-8', errors='replace')
    report['pseudo'] = filled.stdout.strip() or filled.stderr[-800:]
    out = ws / 'build' / 'e2e'
    if out.exists():
        shutil.rmtree(out)
    code, report['build'] = glk(ws, 'build', '--force-draft', '--out', str(out))
    if code == 0:
        steps = []
        for st in a.step:
            steps += ['--step', st]
        report['shots'] = glk(ws, 'shots', '--build', str(out), '--step', f'wait:{a.wait}', '--step', 'shot:start', *steps)[1]
    report['original_changes'] = integrity.verify(w.game_dir, w.path('original-manifest.json'), deep=True)[:5]
    if not a.keep_build and out.exists():
        shutil.rmtree(out)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
