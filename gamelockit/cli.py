"""命令行入口：glk。输出只含统计与路径，不打印原文/译文，避免剧透。"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import catalog, integrity, quality, saveguard
from .adapters import detect, get
from .project import Workspace, read_json, write_json
from .release import make_release
from .supervisor import Supervisor
from .validate import check_target, compile_tokens

LANG_NAMES = {'ja': '日文', 'en': '英文', 'ko': '韩文', 'zh': '繁体/其他中文'}
TEMPLATES = Path(__file__).with_name('templates')
PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def emit(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=1) + '\n')


def load(args):
    ws = Workspace(args.ws)
    adapter = get(ws.engine)(ws)
    return ws, adapter


def glk_command(ws):
    return f'python -m gamelockit --ws "{ws.root.as_posix()}"'


def render_instructions(ws, adapter):
    lang = LANG_NAMES.get(ws.source_lang, ws.source_lang)
    worker = (TEMPLATES / 'worker_instructions.md').read_text(encoding='utf-8').format(
        source_lang_name=lang, glk=glk_command(ws), batch=ws.config['translator']['batch'],
        work_dir=ws.path('work', 'WORKER_ID').as_posix(), engine_notes=adapter.translator_notes or '（无额外标记）')
    ws.path('work').mkdir(exist_ok=True)
    ws.path('work', 'WORKER_INSTRUCTIONS.md').write_text(worker, encoding='utf-8')
    dual = '使用显示层注入，dual 会被放行翻译（内部仍保留原文）。' if adapter.display_layer else '直接替换文本，dual 不会被放行（翻译会改变程序行为）。'
    audit = (TEMPLATES / 'audit_instructions.md').read_text(encoding='utf-8').format(
        source_lang_name=lang, dual_note=dual, unpacked=ws.unpacked.as_posix(), glk=glk_command(ws))
    ws.path('audit').mkdir(exist_ok=True)
    ws.path('audit', 'AUDIT_INSTRUCTIONS.md').write_text(audit, encoding='utf-8')


def cmd_detect(args):
    emit([{'engine': name, 'score': score} for score, name in detect(args.game)])


def cmd_init(args):
    engine = args.engine
    if not engine:
        found = detect(args.game)
        if not found:
            raise SystemExit('无法识别引擎，请用 --engine 指定')
        engine = found[0][1]
    ws = Workspace.create(args.ws, args.game, engine, source_lang=args.source_lang)
    if args.locale:
        ws.config['launch']['locale'] = args.locale
        ws.save()
    adapter = get(engine)(ws)
    count = integrity.record(ws.game_dir, ws.path('original-manifest.json'), exclude=adapter.personal_data_globs)
    render_instructions(ws, adapter)
    emit({'workspace': str(ws.root), 'engine': engine, 'original_files': count})


def cmd_extract(args):
    ws, adapter = load(args)
    adapter.unpack()
    occurrences = list(adapter.extract())
    added = catalog.add_occurrences(ws.db, occurrences, adapter.display_layer)
    render_instructions(ws, adapter)
    emit({'occurrences': len(occurrences), 'new_items': added, **catalog.status(ws.db)})


def cmd_audit(args):
    ws, adapter = load(args)
    if args.action == 'export':
        items = catalog.pending_audit(ws.db)
        folder = ws.path('audit', 'pending')
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob('batch-*.json'):
            old.unlink()
        files = []
        for n in range(0, len(items), args.size):
            path = folder / f'batch-{n // args.size + 1:04d}.json'
            catalog.export_json(path, items[n:n + args.size])
            files.append(path.name)
        emit({'pending': len(items), 'batches': len(files), 'folder': str(folder), 'instructions': str(ws.path('audit', 'AUDIT_INSTRUCTIONS.md'))})
    else:
        decisions = read_json(args.file)
        emit({'applied': catalog.apply_usage(ws.db, decisions, adapter.display_layer), **catalog.status(ws.db)})


def cmd_worker(args):
    ws, adapter = load(args)
    if args.action == 'claim':
        task = catalog.claim(ws.db, args.worker, ws.config['translator']['batch'])
        path = ws.path('work', args.worker, 'task.json')
        catalog.export_json(path, task)
        emit({'task_file': str(path), 'lease': task['lease'], 'items': len(task['items']), 'remaining_total': task['remaining_total']})
    elif args.action == 'submit':
        data = read_json(args.file)
        tokens = compile_tokens(adapter.token_patterns)
        n = catalog.submit(ws.db, args.worker, args.lease, data.get('translations'), data.get('glossary', []), tokens)
        emit({'accepted': n})
    else:
        catalog.release(ws.db, args.worker, args.lease)
        emit({'released': True})


def cmd_translate(args):
    ws, adapter = load(args)
    render_instructions(ws, adapter)
    instructions = ws.path('work', 'WORKER_INSTRUCTIONS.md').as_posix()
    os.environ['PYTHONPATH'] = os.pathsep.join(filter(None, [str(PACKAGE_ROOT), os.environ.get('PYTHONPATH')]))

    def prompt(worker):
        return (f'你是翻译工作进程 {worker}。用 read 完整读取 {instructions}，按其中流程领取并翻译一批。'
                f'所有 WORKER_ID 替换为 {worker}。完成本批即退出。不得向用户输出剧情、专名、原文或译文。')
    emit(Supervisor(ws, prompt).run())


def cmd_import(args):
    """导入已有译文（如旧项目的数据库导出）：[{source,target,usage,reason}]，逐条校验格式。"""
    ws, adapter = load(args)
    tokens = compile_tokens(adapter.token_patterns)
    rows = read_json(args.file)
    decisions, applied, rejected = [], 0, []
    with catalog.connection(ws.db) as con:
        ids = {r['source']: r['id'] for r in con.execute('SELECT id,source FROM items')}
    for row in rows:
        iid = ids.get(row['source'])
        if iid and row.get('usage'):
            decisions.append({'id': iid, 'usage': row['usage'], 'reason': row.get('reason') or 'imported'})
    if decisions:
        catalog.apply_usage(ws.db, decisions, adapter.display_layer)
    now = time.time()
    with catalog.connection(ws.db) as con:
        for row in rows:
            iid = ids.get(row['source'])
            if not iid or row.get('target') is None:
                continue
            if check_target(row['source'], row['target'], tokens):
                rejected.append(iid)
                continue
            con.execute('UPDATE items SET target=?,updated=?,worker=NULL,lease=NULL,expires=NULL WHERE id=? AND released=1', (row['target'], now, iid))
            applied += 1
    emit({'usage_applied': len(decisions), 'targets_applied': applied, 'rejected': len(rejected), 'unknown_sources': sum(1 for r in rows if r['source'] not in ids)})


def cmd_status(args):
    ws, _ = load(args)
    emit({'engine': ws.engine, **catalog.status(ws.db)})


def cmd_check(args):
    ws, adapter = load(args)
    problems = quality.build_gate(ws, compile_tokens(adapter.token_patterns), deep_integrity=args.deep)
    emit({'ok': not problems, 'problems': problems})
    return 0 if not problems else 1


def cmd_build(args):
    ws, adapter = load(args)
    problems = [] if args.force_draft else quality.build_gate(ws, compile_tokens(adapter.token_patterns))
    if problems:
        emit({'ok': False, 'problems': problems})
        return 1
    out = Path(args.out) if args.out else ws.path('build', time.strftime('%Y%m%d-%H%M%S'))
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'输出目录非空，拒绝覆盖: {out}')
    adapter.unpack()
    summary = adapter.build(catalog.mapping(ws.db), out)
    after = integrity.verify(ws.game_dir, ws.path('original-manifest.json'))
    result = {'ok': not after, 'out': str(out), 'draft': bool(args.force_draft), 'summary': summary, 'original_changes': after[:5]}
    if not args.no_probe:
        with saveguard.guard(adapter.shared_save_locations(out), ws.path('save-backup')):
            result['probe'] = adapter.probe(out)
    write_json(out.parent / f'{out.name}.build.json', result)
    emit(result)
    return 0 if result['ok'] else 1


def cmd_residual(args):
    ws, _ = load(args)
    texts = read_json(args.file)
    allow = read_json(args.allow) if args.allow else ()
    found = quality.residual_scan(texts, catalog.mapping(ws.db), ws.source_lang, allow)
    if args.report:
        write_json(args.report, found)
    emit({'texts': len(texts), 'residuals': len(found), 'report': args.report})
    return 0 if not found else 1


OCR_LANG = {'ja': 'ja', 'en': 'en-US', 'ko': 'ko', 'zh': 'zh-Hant-TW'}


def cmd_shots(args):
    """启动汉化副本（按 launch 配置决定是否转区）→ 按步骤截图 → OCR → 残留原文扫描。"""
    from . import capture, ocr
    ws, adapter = load(args)
    build = Path(args.build)
    exe = adapter.launcher(build)
    if not exe:
        raise SystemExit(f'在 {build} 找不到启动文件')
    steps = read_json(args.steps) if args.steps else []
    steps += args.step or []
    if not any(st.startswith('shot:') for st in steps):
        steps += ['wait:10', 'shot:start']
    out = ws.path('shots', f'{build.name}-{time.strftime("%Y%m%d-%H%M%S")}')
    with saveguard.guard(adapter.shared_save_locations(build), ws.path('save-backup')):
        result = capture.run(build / exe, steps, out, ws.config.get('launch'), legacy_codepage=adapter.legacy_codepage)
    texts = []
    if result['shots'] and not args.no_ocr:
        recognized = ocr.recognize(result['shots'], OCR_LANG.get(ws.source_lang, ws.source_lang))
        write_json(out / 'ocr.json', recognized)
        texts = ocr.text_lines(recognized)
        result['ocr_errors'] = sum(1 for v in recognized.values() if isinstance(v, dict))
        allow = read_json(args.allow) if args.allow else ()
        found = quality.residual_scan(texts, catalog.mapping(ws.db), ws.source_lang, allow)
        write_json(out / 'residual.json', found)
        result['residuals'] = len(found)
    result.update(dir=str(out), ocr_lines=len(texts))
    if result['shots'] and not args.no_ocr and not texts:
        # 没读到任何文字时“0 残留”没有意义（可能是纯图片画面或 OCR 语言不对），必须人工看图。
        result['warning'] = 'OCR 未识别到任何文字，残留扫描无效，请人工查看截图'
    emit(result)
    failed = 'error' in result or 'warning' in result or result.get('residuals') or result.get('ocr_errors')
    return 1 if failed else 0


def cmd_release(args):
    ws, adapter = load(args)
    emit(make_release(ws, adapter, args.build, args.out, args.title, not args.no_original))


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        # 管道输出默认随系统代码页（中文系统为 GBK），读取方按 UTF-8 解码会乱码
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(prog='glk', description='多引擎游戏汉化工作流')
    p.add_argument('--ws', help='工作区目录（init 之外的命令必填）')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('detect', help='识别游戏引擎'); s.add_argument('game'); s.set_defaults(fn=cmd_detect)
    s = sub.add_parser('init', help='创建工作区并记录原版清单')
    s.add_argument('game'); s.add_argument('--engine'); s.add_argument('--source-lang', default='ja')
    s.add_argument('--locale', choices=['auto', 'ja', 'none'], help='启动方式：ja=总是转区（光盘版等只能在日文环境运行的游戏）')
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser('extract', help='解包并提取候选文字'); s.set_defaults(fn=cmd_extract)
    s = sub.add_parser('audit', help='用途审核：导出待审批次 / 应用审核结论')
    s.add_argument('action', choices=['export', 'apply']); s.add_argument('file', nargs='?'); s.add_argument('--size', type=int, default=300); s.set_defaults(fn=cmd_audit)
    s = sub.add_parser('worker', help='翻译子 Agent 使用：领取/提交/释放')
    s.add_argument('action', choices=['claim', 'submit', 'release']); s.add_argument('--worker', required=True)
    s.add_argument('--lease'); s.add_argument('--file'); s.set_defaults(fn=cmd_worker)
    s = sub.add_parser('translate', help='启动翻译调度（子 Agent）'); s.set_defaults(fn=cmd_translate)
    s = sub.add_parser('import', help='导入已有用途结论与译文'); s.add_argument('file'); s.set_defaults(fn=cmd_import)
    s = sub.add_parser('status', help='进度'); s.set_defaults(fn=cmd_status)
    s = sub.add_parser('check', help='打包门禁检查'); s.add_argument('--deep', action='store_true'); s.set_defaults(fn=cmd_check)
    s = sub.add_parser('build', help='通过门禁后生成独立汉化副本')
    s.add_argument('--out'); s.add_argument('--no-probe', action='store_true')
    s.add_argument('--force-draft', action='store_true', help='跳过门禁生成测试草稿（不可发布）'); s.set_defaults(fn=cmd_build)
    s = sub.add_parser('residual', help='扫描画面文字中的残留原文')
    s.add_argument('file'); s.add_argument('--allow'); s.add_argument('--report'); s.set_defaults(fn=cmd_residual)
    s = sub.add_parser('shots', help='启动汉化副本截图并 OCR 扫描残留原文（需要时自动转区）')
    s.add_argument('--build', required=True, help='glk build 生成的副本目录')
    s.add_argument('--steps', help='步骤 JSON 列表文件'); s.add_argument('--step', action='append', help='单个步骤，可重复，如 wait:10 / click:330,350 / key:enter / shot:名称')
    s.add_argument('--allow', help='按约定不翻的原文 JSON 列表'); s.add_argument('--no-ocr', action='store_true'); s.set_defaults(fn=cmd_shots)
    s = sub.add_parser('release', help='生成 原版/ 与 汉化版/ 分发目录')
    s.add_argument('--build', required=True); s.add_argument('--out', required=True); s.add_argument('--title')
    s.add_argument('--no-original', action='store_true'); s.set_defaults(fn=cmd_release)
    args = p.parse_args(argv)
    if args.cmd == 'init':
        if not args.ws:
            p.error('init 需要 --ws')
    elif args.cmd != 'detect' and not args.ws:
        p.error('需要 --ws 工作区目录')
    for stream in (sys.stdout, sys.stderr):
        if stream.encoding and stream.encoding.lower() != 'utf-8':
            stream.reconfigure(encoding='utf-8')
    try:
        return args.fn(args) or 0
    except (ValueError, RuntimeError, OSError) as exc:
        # 预期内的失败（数据/环境问题）只给出原因；设置 GLK_DEBUG=1 可看完整堆栈
        if os.environ.get('GLK_DEBUG'):
            raise
        emit({'ok': False, 'error': f'{type(exc).__name__}: {exc}'})
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
