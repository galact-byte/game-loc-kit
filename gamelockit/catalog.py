"""目录库：去重后的原文条目、出处、用途审核结论、翻译租约与词表。

用途（usage）是放行翻译的唯一依据：
  pending    未审核，不放行（默认）
  display    纯显示文字，放行
  dual       同时参与程序判断的显示文字；仅当适配器使用显示层注入时放行
  protected  参与逻辑/标识/路径/调试等，不翻译
  excluded   不需要翻译（玩家输入、作者注释、未显示字段等）
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .validate import check_target

USAGES = ('pending', 'display', 'dual', 'protected', 'excluded')
WORKER_ID = re.compile(r'[A-Za-z0-9_-]{1,50}')
GLOSSARY_CATEGORIES = ('person', 'place', 'special')
LEASE_TTL = 1800

SCHEMA = '''
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY, source TEXT NOT NULL UNIQUE, usage TEXT NOT NULL DEFAULT 'pending',
  reason TEXT, released INTEGER NOT NULL DEFAULT 0, target TEXT,
  worker TEXT, lease TEXT, expires REAL, updated REAL);
CREATE TABLE IF NOT EXISTS refs (
  item_id TEXT NOT NULL, surface TEXT NOT NULL, ref TEXT NOT NULL, context TEXT, hint TEXT,
  PRIMARY KEY(item_id, surface, ref));
CREATE TABLE IF NOT EXISTS quarantine (id TEXT PRIMARY KEY, reason TEXT NOT NULL, worker TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS glossary (source TEXT PRIMARY KEY, target TEXT NOT NULL, category TEXT NOT NULL, worker TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS glossary_conflicts (source TEXT, existing TEXT, proposed TEXT, worker TEXT, created REAL);
'''


def item_id(source):
    return hashlib.sha1(source.encode('utf-8')).hexdigest()[:16]


@contextmanager
def connection(db):
    Path(db).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=30000')
    try:
        con.executescript(SCHEMA)
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def add_occurrences(db, occurrences, allow_dual):
    """导入提取结果；已有审核结论不被覆盖。返回新增条目数。"""
    added = 0
    with connection(db) as con:
        for occ in occurrences:
            iid = item_id(occ.source)
            if con.execute('INSERT OR IGNORE INTO items(id,source) VALUES(?,?)', (iid, occ.source)).rowcount:
                added += 1
                # 适配器只能把“结构上确定只用于显示”的出处预标为 display，其余一律待审。
                if occ.hint == 'display':
                    _set_usage(con, iid, 'display', 'adapter:' + occ.surface, allow_dual)
                elif occ.hint in ('protected', 'excluded'):
                    _set_usage(con, iid, occ.hint, 'adapter:' + occ.surface, allow_dual)
            con.execute('INSERT OR REPLACE INTO refs VALUES(?,?,?,?,?)', (iid, occ.surface, occ.ref, occ.context, occ.hint))
    return added


def _set_usage(con, iid, usage, reason, allow_dual):
    if usage not in USAGES:
        raise ValueError(f'未知用途: {usage}')
    if con.execute('SELECT 1 FROM quarantine WHERE id=?', (iid,)).fetchone():
        released = 0
    else:
        released = int(usage == 'display' or (usage == 'dual' and allow_dual))
    con.execute('UPDATE items SET usage=?,reason=?,released=? WHERE id=?', (usage, reason, released, iid))
    if not released:
        con.execute('UPDATE items SET worker=NULL,lease=NULL,expires=NULL WHERE id=? AND target IS NULL', (iid,))


def apply_usage(db, decisions, allow_dual):
    """decisions: [{id, usage, reason}]；整批校验通过才写入。"""
    if not isinstance(decisions, list) or not decisions:
        raise ValueError('审核结论必须是非空数组')
    with connection(db) as con:
        for d in decisions:
            if not isinstance(d, dict) or d.get('usage') not in USAGES or d['usage'] == 'pending':
                raise ValueError(f'审核结论无效: {d!r:.80}')
            if not isinstance(d.get('reason'), str) or not d['reason'].strip():
                raise ValueError(f'{d.get("id")}: 必须写明理由')
            if not con.execute('SELECT 1 FROM items WHERE id=?', (d.get('id'),)).fetchone():
                raise ValueError(f'条目不存在: {d.get("id")}')
            _set_usage(con, d['id'], d['usage'], d['reason'].strip(), allow_dual)
    return len(decisions)


def pending_audit(db, limit=None):
    with connection(db) as con:
        rows = con.execute("SELECT id,source FROM items WHERE usage='pending' ORDER BY rowid" + (' LIMIT ?' if limit else ''), (limit,) if limit else ()).fetchall()
        return [{'id': r['id'], 'source': r['source'], 'refs': refs_of(con, r['id'])} for r in rows]


def refs_of(con, iid, limit=6):
    return [dict(r) for r in con.execute('SELECT surface,ref,context,hint FROM refs WHERE item_id=? LIMIT ?', (iid, limit))]


def _reclaim(con, now):
    con.execute('UPDATE items SET worker=NULL,lease=NULL,expires=NULL WHERE target IS NULL AND expires<=?', (now,))


def claim(db, worker, limit=300, now=None):
    now = time.time() if now is None else now
    if not WORKER_ID.fullmatch(worker) or not 1 <= limit <= 300:
        raise ValueError('worker 或批次大小非法')
    with connection(db) as con:
        _reclaim(con, now)
        rows = con.execute('SELECT * FROM items WHERE released=1 AND target IS NULL AND worker=? ORDER BY rowid', (worker,)).fetchall()
        lease = rows[0]['lease'] if rows else uuid.uuid4().hex
        if not rows:
            rows = con.execute('SELECT * FROM items WHERE released=1 AND target IS NULL AND worker IS NULL ORDER BY rowid LIMIT ?', (limit,)).fetchall()
        for row in rows:
            con.execute('UPDATE items SET worker=?,lease=?,expires=? WHERE id=?', (worker, lease, now + LEASE_TTL, row['id']))
        glossary = [dict(r) for r in con.execute('SELECT source,target,category FROM glossary ORDER BY source')]
        remaining = con.execute('SELECT count(*) FROM items WHERE released=1 AND target IS NULL').fetchone()[0]
        return {'worker': worker, 'lease': lease, 'expires': now + LEASE_TTL, 'remaining_total': remaining, 'glossary': glossary,
                'items': [{'id': r['id'], 'source': r['source'], 'refs': refs_of(con, r['id'], 4)} for r in rows]}


def submit(db, worker, lease, translations, glossary, tokens, now=None):
    now = time.time() if now is None else now
    if not isinstance(translations, list) or not translations:
        raise ValueError('提交必须包含译文数组')
    with connection(db) as con:
        seen = set()
        for item in translations:
            iid = item.get('id')
            if iid in seen:
                raise ValueError('提交含重复 ID')
            seen.add(iid)
            row = con.execute('SELECT * FROM items WHERE id=?', (iid,)).fetchone()
            if row is None or not row['released'] or row['worker'] != worker or row['lease'] != lease or (row['expires'] or 0) <= now or row['target'] is not None:
                raise ValueError(f'任务不属于有效租约或已完成：{iid}')
            errors = check_target(row['source'], item.get('target'), tokens)
            if errors:
                raise ValueError(f'{iid}: {"；".join(errors)}')
            con.execute('UPDATE items SET target=?,updated=? WHERE id=?', (item['target'], now, iid))
        for term in glossary or []:
            if term.get('category') not in GLOSSARY_CATEGORIES or not all(isinstance(term.get(k), str) and term[k].strip() and len(term[k]) <= 100 for k in ('source', 'target')):
                raise ValueError('词表仅允许人物、地点、专用词汇的短映射')
            old = con.execute('SELECT target FROM glossary WHERE source=?', (term['source'],)).fetchone()
            if old is None:
                con.execute('INSERT INTO glossary VALUES(?,?,?,?)', (term['source'], term['target'], term['category'], worker))
            elif old['target'] != term['target']:
                con.execute('INSERT INTO glossary_conflicts VALUES(?,?,?,?,?)', (term['source'], old['target'], term['target'], worker, now))
        con.execute('UPDATE items SET expires=? WHERE worker=? AND lease=? AND target IS NULL', (now + LEASE_TTL, worker, lease))
    return len(translations)


def release(db, worker, lease=None):
    with connection(db) as con:
        sql = 'UPDATE items SET worker=NULL,lease=NULL,expires=NULL WHERE worker=? AND target IS NULL'
        con.execute(sql + (' AND lease=?' if lease else ''), (worker, lease) if lease else (worker,))


def quarantine(db, worker, reports):
    """工作进程报告无法安全翻译的条目：撤销放行，等主控人工复核。"""
    if not isinstance(reports, list) or not reports:
        raise ValueError('缺少需审核的条目')
    with connection(db) as con:
        for report in reports:
            row = con.execute('SELECT worker FROM items WHERE id=?', (report.get('id'),)).fetchone()
            reason = report.get('category', '')
            if row is None or row['worker'] not in (None, worker) or not isinstance(reason, str) or not reason.strip():
                raise ValueError('需审核条目不属于该工作进程或原因无效')
            con.execute('INSERT OR IGNORE INTO quarantine VALUES(?,?,?,?)', (report['id'], reason, worker, time.time()))
            con.execute('UPDATE items SET released=0,worker=NULL,lease=NULL,expires=NULL WHERE id=?', (report['id'],))
    return len(reports)


def status(db):
    with connection(db) as con:
        usage = {r[0]: r[1] for r in con.execute('SELECT usage,count(*) FROM items GROUP BY usage')}
        released, done, leased = con.execute('SELECT count(*),count(target),coalesce(sum(CASE WHEN target IS NULL AND worker IS NOT NULL THEN 1 ELSE 0 END),0) FROM items WHERE released=1').fetchone()
        conflicts = con.execute('SELECT count(*) FROM glossary_conflicts').fetchone()[0]
        quarantined = con.execute('SELECT count(*) FROM quarantine').fetchone()[0]
    return {'usage': usage, 'released': released, 'translated': done, 'leased': leased,
            'pending_translation': released - done, 'glossary_conflicts': conflicts, 'quarantined': quarantined}


def mapping(db):
    """已放行且已翻译的 原文→译文。"""
    with connection(db) as con:
        return dict(con.execute('SELECT source,target FROM items WHERE released=1 AND target IS NOT NULL'))


def all_targets(db):
    with connection(db) as con:
        return [dict(r) for r in con.execute('SELECT id,source,target FROM items WHERE released=1')]


def export_json(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding='utf-8')
