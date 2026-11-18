import csv
import io

from flask import Blueprint, Response, jsonify, request

from app import ledger
from app.errors import DomainError
from app.numeric import serial
from app.pipeline import calculate
from app.reconcile import EVIDENCE_FIELDS, rows as reconciliation_rows
from app.store import get_run, latest

bp = Blueprint('m8', __name__)


@bp.route('/api/m8', methods=['GET', 'POST'])
def module_8():
    payload = request.get_json(silent=True) or {}
    result = calculate(payload.get('csv'), stop=8)
    # Overlay the live local ledger so the standalone module shows the same
    # reconciliation as the stored batch page.
    return jsonify(serial(ledger.present(result)['stages']['8']))


@bp.route('/api/contracts', methods=['GET', 'POST'])
def contracts():
    if request.method == 'GET':
        return jsonify(ledger.contract_list(request.args.get('scene')))
    body = request.get_json(silent=True) or {}
    items = body.get('contracts') if 'contracts' in body else [body]
    return jsonify({'contracts': ledger.create_contracts(items)}), 201


@bp.route('/api/contracts/import', methods=['POST'])
def contracts_import():
    body = request.get_json(silent=True) or {}
    text = body.get('csv')
    if not isinstance(text, str) or not text.strip():
        raise DomainError('LEDGER', '合同CSV不能为空', 400)
    return jsonify({'contracts': ledger.import_contracts(text)}), 201


@bp.route('/api/contracts/<ident>')
def contract_detail(ident):
    item = ledger.contract(ident)
    if item is None:
        raise DomainError('NOT_FOUND', '合同不存在', 404)
    return jsonify(item)


@bp.route('/api/payments', methods=['GET', 'POST'])
def payments():
    if request.method == 'GET':
        return jsonify(ledger.payment_list(request.args.get('contract')))
    return jsonify(ledger.add_payment(request.get_json(silent=True) or {})), 201


@bp.route('/api/payments/import', methods=['POST'])
def payments_import():
    body = request.get_json(silent=True) or {}
    text = body.get('csv')
    if not isinstance(text, str) or not text.strip():
        raise DomainError('LEDGER', '付款CSV不能为空', 400)
    return jsonify({'payments': ledger.import_payments(text)}), 201


@bp.route('/api/commit', methods=['POST'])
def commit():
    body = request.get_json(silent=True) or {}
    run_id = body.get('run_id') or body.get('id')
    if not run_id:
        raise DomainError('COMMIT', '缺少批次号', 400)
    return jsonify(ledger.commit(get_run(run_id)))


def _selected():
    run_id = request.args.get('run_id')
    return get_run(run_id) if run_id else (latest() or calculate())


@bp.route('/api/reconciliation')
def reconciliation():
    return jsonify(ledger.reconcile_run(_selected()))


@bp.route('/api/reconciliation.csv')
def reconciliation_csv():
    result = _selected()
    reconciliation = ledger.reconcile_run(result)
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=['run_id', '对账目录修订'] + EVIDENCE_FIELDS)
    writer.writeheader()
    for row in reconciliation_rows(reconciliation):
        writer.writerow({'run_id': result['manifest']['run_id'], '对账目录修订': reconciliation['catalogue']['id'], **row})
    return Response('﻿' + out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=reconciliation.csv'})
