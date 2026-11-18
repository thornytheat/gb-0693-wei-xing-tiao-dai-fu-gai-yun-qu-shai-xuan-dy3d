"""Immutable contract and payment ledger.

Signed contracts and payments are append-only.  The ``scene`` stored on a
contract is the number written on the signed paper and is never rewritten;
later catalogue revisions may merge it with another number, but this module
only records that fact.  Reconciliation is where old and current numbers are
shown side by side.
"""
import hashlib
import json
import time
from decimal import Decimal

from app import catalog
from app.db import connection
from app.errors import DomainError
from app.numeric import number


def _now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def _text(value, field):
    if value is None:
        raise DomainError('CONTRACT', field + '不能为空')
    text = str(value).strip()
    if not text:
        raise DomainError('CONTRACT', field + '不能为空')
    return text


def _optional(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _contract_row(row):
    payload = json.loads(row['payload'])
    return {
        'id': row['id'],
        'contract_no': row['contract_no'],
        'scene': row['scene'],
        'price': row['price'],
        'signed_at': row['signed_at'],
        'catalogue_id': row['catalogue_id'],
        'run_id': row['run_id'],
        'created_at': row['created_at'],
        'canonical_at_signing': payload.get('canonical_at_signing'),
        'note': payload.get('note'),
        'scene_locked': True,
    }


def _payment_row(row):
    return {
        'id': row['id'],
        'contract_id': row['contract_id'],
        'amount': row['amount'],
        'paid_at': row['paid_at'],
        'note': row['note'],
        'created_at': row['created_at'],
    }


def _paid(db, contract_id):
    rows = db.execute('SELECT amount FROM payments WHERE contract_id=?', (contract_id,)).fetchall()
    return sum((Decimal(row['amount']) for row in rows), Decimal(0))


def _inspect(data):
    if not isinstance(data, dict):
        raise DomainError('CONTRACT', '合同必须是对象')
    contract_no = _text(data.get('contract_no', data.get('合同号')), '合同号')
    scene = _text(data.get('scene', data.get('场景号')), '场景号')
    try:
        price = number(data.get('price', data.get('价格')))
    except DomainError as error:
        raise DomainError('CONTRACT', '合同价格无效：' + error.message)
    if price < 0:
        raise DomainError('CONTRACT', '合同价格不能为负')
    return {
        'contract_no': contract_no,
        'scene': scene,
        'price': price,
        'signed_at': _optional(data.get('signed_at', data.get('签约时间'))),
        'catalogue_id': _optional(data.get('catalogue_id')),
        'run_id': _optional(data.get('run_id')),
        'canonical_at_signing': data.get('canonical_at_signing', data.get('签约时目录编号')),
        'note': _optional(data.get('note', data.get('备注'))),
    }


def _same(existing, wanted):
    return (
        existing['contract_no'] == wanted['contract_no']
        and existing['scene'] == wanted['scene']
        and Decimal(existing['price']) == wanted['price']
        and existing['signed_at'] == wanted['signed_at']
    )


def _insert(data, db):
    ident = 'contract:' + data['contract_no']
    ident = hashlib.sha256(ident.encode('utf-8')).hexdigest()[:16]
    payload = {'canonical_at_signing': data['canonical_at_signing'], 'note': data['note']}
    db.execute(
        'INSERT INTO contracts(id,contract_no,scene,price,signed_at,catalogue_id,run_id,created_at,payload) VALUES(?,?,?,?,?,?,?,?,?)',
        (ident, data['contract_no'], data['scene'], str(data['price']), data['signed_at'], data['catalogue_id'], data['run_id'], _now(), json.dumps(payload, ensure_ascii=False)),
    )
    return db.execute('SELECT * FROM contracts WHERE id=?', (ident,)).fetchone()


def create_contract(data, db=None):
    """Register one signed contract.

    Re-posting the identical signed contract returns the stored row.  Posting
    a different body under an existing contract number is refused with 409:
    signed contracts cannot be rewritten.
    """
    wanted = _inspect(data)
    own = db is None
    if own:
        db = connection()
    try:
        existing = db.execute('SELECT * FROM contracts WHERE contract_no=?', (wanted['contract_no'],)).fetchone()
        if existing:
            row = _contract_row(existing)
            if not _same(existing, wanted):
                raise DomainError('CONTRACT_LOCKED', '合同号已存在且内容不同，已签合同不可改写', 409)
            return {**row, 'reused': True}
        row = _insert(wanted, db)
        if own:
            db.commit()
        return {**_contract_row(row), 'reused': False}
    except Exception:
        if own:
            db.rollback()
        raise
    finally:
        if own:
            db.close()


def create_contracts(items):
    if not isinstance(items, list) or not items:
        raise DomainError('CONTRACT', '合同列表不能为空')
    db = connection()
    try:
        created = [create_contract(item, db) for item in items]
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return created


def _decorate(db, row):
    active = catalog.active()
    identity = active['identity'] if active else {}
    item = _contract_row(row)
    item['paid'] = str(_paid(db, row['id']))
    item['canonical_now'] = identity.get(row['scene'])
    item['catalogue_seq'] = active['seq'] if active else None
    return item


def contract_list(scene=None):
    with connection() as db:
        rows = db.execute('SELECT * FROM contracts ORDER BY created_at, contract_no').fetchall()
        answer = [_decorate(db, row) for row in rows]
        if scene is not None:
            scene = str(scene)
            answer = [item for item in answer if item['scene'] == scene or item['canonical_now'] == scene]
    return answer


def contract(ident):
    with connection() as db:
        row = db.execute('SELECT * FROM contracts WHERE id=? OR contract_no=?', (ident, ident)).fetchone()
        if row is None:
            return None
        item = _decorate(db, row)
        item['payments'] = [_payment_row(p) for p in db.execute('SELECT * FROM payments WHERE contract_id=? ORDER BY created_at, id', (row['id'],)).fetchall()]
    return item


def add_payment(data):
    if not isinstance(data, dict):
        raise DomainError('PAYMENT', '付款必须是对象')
    ident = data.get('contract_id') or data.get('contract_no') or data.get('合同号')
    ident = _text(ident, '合同号')
    try:
        amount = number(data.get('amount', data.get('金额')))
    except DomainError as error:
        raise DomainError('PAYMENT', '付款金额无效：' + error.message)
    if amount <= 0:
        raise DomainError('PAYMENT', '付款金额必须为正')
    paid_at = _optional(data.get('paid_at', data.get('付款时间')))
    note = _optional(data.get('note', data.get('备注')))
    payment_id = hashlib.sha256((':'.join([ident, str(amount), paid_at or '', note or ''])).encode('utf-8')).hexdigest()[:16]
    with connection() as db:
        row = db.execute('SELECT id FROM contracts WHERE id=? OR contract_no=?', (ident, ident)).fetchone()
        if row is None:
            raise DomainError('NOT_FOUND', '合同不存在', 404)
        existing = db.execute('SELECT * FROM payments WHERE id=?', (payment_id,)).fetchone()
        if existing:
            return {**_payment_row(existing), 'reused': True}
        db.execute(
            'INSERT INTO payments(id,contract_id,amount,paid_at,note,created_at) VALUES(?,?,?,?,?,?)',
            (payment_id, row['id'], str(amount), paid_at, note, _now()),
        )
        created = db.execute('SELECT * FROM payments WHERE id=?', (payment_id,)).fetchone()
    return {**_payment_row(created), 'reused': False}


def payment_list(contract=None):
    with connection() as db:
        rows = db.execute('SELECT p.*, c.contract_no, c.scene FROM payments p JOIN contracts c ON c.id=p.contract_id ORDER BY p.created_at, p.id').fetchall()
    answer = []
    for row in rows:
        item = _payment_row(row)
        item['contract_no'] = row['contract_no']
        item['scene'] = row['scene']
        answer.append(item)
    if contract is None:
        return answer
    return [item for item in answer if item['contract_id'] == contract or item['contract_no'] == contract]


def _csv_rows(text):
    import csv
    import io
    reader = csv.DictReader(io.StringIO(text.lstrip('﻿'), newline=''))
    if reader.fieldnames is None:
        raise DomainError('LEDGER', '台账CSV为空')
    return [{str(k).strip(): (v or '').strip() for k, v in row.items() if k is not None} for row in reader]


def import_contracts(text):
    rows = _csv_rows(text)
    if not rows:
        raise DomainError('LEDGER', '台账CSV没有业务记录')
    items = []
    for row in rows:
        items.append({
            'contract_no': row.get('contract_no') or row.get('合同号'),
            'scene': row.get('scene') or row.get('场景号'),
            'price': row.get('price') or row.get('价格'),
            'signed_at': row.get('signed_at') or row.get('签约时间'),
            'catalogue_id': row.get('catalogue_id') or row.get('目录修订'),
            'note': row.get('note') or row.get('备注'),
        })
    return create_contracts(items)


def import_payments(text):
    rows = _csv_rows(text)
    if not rows:
        raise DomainError('LEDGER', '付款CSV没有业务记录')
    return [add_payment({
        'contract_no': row.get('contract_no') or row.get('合同号'),
        'amount': row.get('amount') or row.get('金额'),
        'paid_at': row.get('paid_at') or row.get('付款时间'),
        'note': row.get('note') or row.get('备注'),
    }) for row in rows]


def reconcile_run(result):
    """Build the live reconciliation of a stored batch against the ledger.

    The plan is the batch snapshot; contracts and payments are read live so a
    contract signed after the batch still appears.  Scene numbers are resolved
    through the batch's own catalogue revision.
    """
    from app.reconcile import build

    run_id = result['manifest']['run_id']
    revision = catalog.get(run_id)
    active = {
        'id': revision['id'] if revision else run_id,
        'seq': revision['seq'] if revision else None,
        'digest': revision['digest'] if revision else result['manifest']['sha256'],
        'created_at': revision['created_at'] if revision else result['manifest']['created_at'],
        'identity': (revision['identity'] if revision else result.get('identity', {})),
    }
    return build(result, contract_list(), payment_list(), active)


def present(result):
    """Return ``result`` with stage 8 recomputed against the live ledger."""
    from app.reconcile import rows
    from app.numeric import serial

    reconciliation = reconcile_run(result)
    totals = reconciliation['totals']
    stage = {
        'rows': rows(reconciliation),
        'metrics': [
            ['计划场景', totals['plan_scenes'], '幅'],
            ['新增采购', totals['new_scenes'], '幅'],
            ['已签约复用', totals['signed_scenes'], '幅'],
            ['新增采购额', totals['new_cost'], 'CNY'],
            ['避免重复', totals['avoided_cost'], 'CNY'],
            ['重复签约', totals['duplicate_cost'], 'CNY'],
        ],
        'contracts': reconciliation['contracts'],
        'payments': reconciliation['payments'],
        'totals': totals,
        'catalogue': reconciliation['catalogue'],
        'stage': 8,
        'name': '采购对账',
        'issues': result['stages'].get('7', {}).get('issues', {}),
        'new_quarantine': 0,
    }
    result = dict(result)
    result['stages'] = dict(result['stages'])
    result['stages']['8'] = serial(stage)
    return result


def committed(run_id):
    with connection() as db:
        row = db.execute('SELECT payload FROM commits WHERE run_id=?', (run_id,)).fetchone()
    return json.loads(row['payload']) if row else None


def commit(result):
    """Turn a batch's net-new plan into contracts exactly once.

    The run id is the idempotency key.  A retry returns the contract list
    created by the first commit and never inserts a second set.
    """
    from app.reconcile import build

    run_id = result['manifest']['run_id']
    done = committed(run_id)
    if done:
        return {**done, 'reused': True}

    revision = catalog.get(run_id) or catalog.record(result)
    if revision is None:
        revision = catalog.activate(result)
    reconciliation = build(result, contract_list(), payment_list(), revision)
    new_rows = [row for row in reconciliation['plan'] if row['status'] == '新增采购']
    skipped = [row for row in reconciliation['plan'] if row['status'] != '新增采购']

    db = connection()
    try:
        # Serialize the check-then-insert so two concurrent retries cannot both
        # miss the commit row and insert a second set of contracts.
        db.execute('BEGIN IMMEDIATE')
        done = db.execute('SELECT payload FROM commits WHERE run_id=?', (run_id,)).fetchone()
        if done:
            db.rollback()
            return {**json.loads(done['payload']), 'reused': True}
        created = []
        for index, row in enumerate(new_rows, start=1):
            item = create_contract({
                'contract_no': 'PC-' + run_id[:8] + '-' + format(index, '02d'),
                'scene': row['scene'],
                'price': row['price'],
                'signed_at': _now(),
                'catalogue_id': revision['id'],
                'run_id': run_id,
                'canonical_at_signing': row['canonical'],
                'note': '由采购批次 ' + run_id + ' 生成',
            }, db)
            created.append({'id': item['id'], 'contract_no': item['contract_no'], 'scene': item['scene'], 'canonical': row['canonical'], 'price': item['price']})
        payload = {
            'run_id': run_id,
            'catalogue_id': revision['id'],
            'created': created,
            'skipped': [{'scene': row['scene'], 'contract_scenes': row['contract_scenes'], 'reason': row['status']} for row in skipped],
            'created_at': _now(),
        }
        db.execute('INSERT INTO commits(run_id,created_at,payload) VALUES(?,?,?)', (run_id, payload['created_at'], json.dumps(payload, ensure_ascii=False)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return {**payload, 'reused': False}
