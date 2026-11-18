import csv
import io

import pytest

HEAD = 'scene,alias,west,east,cloud_w,cloud_e,quality,price,captured,version\n'


def catalogue(*rows):
    body = ''.join(','.join(str(cell) for cell in row) + '\n' for row in rows)
    return HEAD + body


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('APP_DB', str(tmp_path / 'db.sqlite3'))
    from app.main import app
    app.config['TESTING'] = True
    return app.test_client()


def run(client, text):
    response = client.post('/api/run', json={'csv': text})
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def contracts(client):
    return client.get('/api/contracts').get_json()


def m8(client, ident):
    return client.get('/api/runs/' + ident).get_json()['stages']['8']


def test_revision_merges_old_numbers_into_one_plan_row(client):
    first = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    assert [row['场景'] for row in client.get('/api/runs/' + first['manifest']['run_id']).get_json()['stages']['6']['rows']] == ['IMG-A', 'IMG-B']

    second = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', 'IMG-A', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    plan = m8(client, second['manifest']['run_id'])['rows']
    plan = [row for row in plan if row['种类'] == '采购计划']
    assert len(plan) == 1 and plan[0]['当前目录编号'] == 'IMG-A'
    assert plan[0]['合同原编号'] == '—'


def test_signed_contract_keeps_original_number_and_blocks_duplicate_purchase(client):
    run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    assert client.post('/api/contracts', json={'contracts': [
        {'contract_no': 'HT-A', 'scene': 'IMG-A', 'price': '40'},
        {'contract_no': 'HT-B', 'scene': 'IMG-B', 'price': '41'},
    ]}).status_code == 201
    assert client.post('/api/payments', json={'contract_no': 'HT-B', 'amount': '41', 'paid_at': '2026-10-20'}).status_code == 201

    merged = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', 'IMG-A', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    stage = m8(client, merged['manifest']['run_id'])
    plan = [row for row in stage['rows'] if row['种类'] == '采购计划']
    assert len(plan) == 1
    assert plan[0]['状态'] == '已签约'
    assert plan[0]['合同原编号'] == 'IMG-A、IMG-B'

    by_no = {row['合同号']: row for row in stage['rows'] if row['种类'] == '已签合同'}
    assert by_no['HT-A']['合同原编号'] == 'IMG-A'
    assert by_no['HT-B']['合同原编号'] == 'IMG-B'
    assert by_no['HT-B']['当前目录编号'] == 'IMG-A'
    assert by_no['HT-B']['编号对照'] == '目录已归并至 IMG-A'
    assert by_no['HT-B']['状态'] == '重复签约'
    assert stage['totals']['duplicate_scenes'] == 1
    assert stage['totals']['duplicate_cost'] == '41.0000'

    commit = client.post('/api/commit', json={'run_id': merged['manifest']['run_id']}).get_json()
    assert commit['created'] == []
    assert len(contracts(client)) == 2


def test_retry_same_batch_adds_no_contracts(client):
    result = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    ident = result['manifest']['run_id']
    first = client.post('/api/commit', json={'run_id': ident}).get_json()
    again = client.post('/api/commit', json={'run_id': ident}).get_json()
    assert first['reused'] is False and again['reused'] is True
    assert [c['contract_no'] for c in first['created']] == [c['contract_no'] for c in again['created']]
    assert len(contracts(client)) == len(first['created'])


def test_contract_cannot_be_rewritten(client):
    created = client.post('/api/contracts', json={'contract_no': 'HT-1', 'scene': 'IMG-A', 'price': '40'})
    assert created.status_code == 201
    same = client.post('/api/contracts', json={'contract_no': 'HT-1', 'scene': 'IMG-A', 'price': '40'})
    assert same.status_code == 201 and same.get_json()['contracts'][0]['reused'] is True
    changed = client.post('/api/contracts', json={'contract_no': 'HT-1', 'scene': 'IMG-B', 'price': '40'})
    assert changed.status_code == 409
    assert client.get('/api/contracts/HT-1').get_json()['scene'] == 'IMG-A'


def test_catalogue_switch_failure_keeps_previous_revision_active(client):
    first = run(client, catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    second = run(client, catalogue(['IMG-B', '', '170', '172', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1']))
    assert client.get('/api/catalogues/active').get_json()['id'] == second['manifest']['run_id']
    failed = client.post('/api/catalogues/switch', json={'id': 'missing-revision'})
    assert failed.status_code == 404
    assert client.get('/api/catalogues/active').get_json()['id'] == second['manifest']['run_id']
    page = client.get('/work/6').data.decode()
    assert second['manifest']['run_id'][:8] in page


def test_failed_activation_returns_warning_and_previous_page(client, monkeypatch):
    first = run(client, catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    import app.main as main
    def boom(result):
        raise RuntimeError('disk full')
    monkeypatch.setattr(main.catalog, 'activate', boom)
    second = client.post('/api/run', json={'csv': catalogue(['IMG-B', '', '170', '172', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'])}).get_json()
    assert '目录切换失败' in second['warning']
    assert client.get('/api/catalogues/active').get_json()['id'] == first['manifest']['run_id']
    page = client.get('/work/1').data.decode()
    assert first['manifest']['run_id'][:8] in page


def test_reconciliation_page_and_export_show_before_after_numbers(client):
    run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    client.post('/api/contracts', json={'contract_no': 'HT-B', 'scene': 'IMG-B', 'price': '41'})
    client.post('/api/payments', json={'contract_no': 'HT-B', 'amount': '41', 'paid_at': '2026-10-20'})
    merged = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', 'IMG-A', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    ident = merged['manifest']['run_id']

    page = client.get('/work/8?run_id=' + ident).data.decode()
    assert 'IMG-B' in page and 'IMG-A' in page and '目录已归并至 IMG-A' in page

    text = client.get('/api/evidence.csv?run_id=' + ident).data.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(text)))
    contract = next(row for row in rows if row.get('合同号') == 'HT-B' and row['种类'] == '已签合同')
    assert contract['合同原编号'] == 'IMG-B'
    assert contract['当前目录编号'] == 'IMG-A'
    assert contract['编号对照'] == '目录已归并至 IMG-A'
    payment = next(row for row in rows if row['种类'] == '付款记录')
    assert payment['合同原编号'] == 'IMG-B' and payment['当前目录编号'] == 'IMG-A'


def test_payments_are_append_only_and_idempotent(client):
    run(client, catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    client.post('/api/contracts', json={'contract_no': 'HT-A', 'scene': 'IMG-A', 'price': '40'})
    first = client.post('/api/payments', json={'contract_no': 'HT-A', 'amount': '10', 'paid_at': '2026-10-01'}).get_json()
    again = client.post('/api/payments', json={'contract_no': 'HT-A', 'amount': '10', 'paid_at': '2026-10-01'}).get_json()
    assert first['reused'] is False and again['reused'] is True
    client.post('/api/payments', json={'contract_no': 'HT-A', 'amount': '5', 'paid_at': '2026-10-02'})
    listing = client.get('/api/payments?contract=HT-A').get_json()
    assert len(listing) == 2
    assert client.get('/api/contracts/HT-A').get_json()['paid'] == '15'


def test_catalogue_is_local_only(client):
    # Everything is served from the local SQLite file and bundled CSV.
    run(client, catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    active = client.get('/api/catalogues/active').get_json()
    assert active['id'] and active['identity']['IMG-A'] == 'IMG-A'
    history = client.get('/api/catalogues').get_json()
    assert len(history) == 1 and history[0]['active'] is True


def test_locked_scene_survives_revision_that_drops_it(client):
    run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    client.post('/api/contracts', json={'contract_no': 'HT-B', 'scene': 'IMG-B', 'price': '41'})
    later = run(client, catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    stage = m8(client, later['manifest']['run_id'])
    row = next(r for r in stage['rows'] if r.get('合同号') == 'HT-B')
    assert row['合同原编号'] == 'IMG-B'
    assert row['编号对照'] == '目录未收录'
    assert row['状态'] == '计划外'


def test_renamed_number_keeps_old_contract_lookup(client):
    first = run(client, catalogue(['IMG-OLD', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    client.post('/api/contracts', json={'contract_no': 'HT-OLD', 'scene': 'IMG-OLD', 'price': '40'})
    renamed = run(client, catalogue(['IMG-NEW', 'IMG-OLD', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1']))
    stage = m8(client, renamed['manifest']['run_id'])
    plan = [row for row in stage['rows'] if row['种类'] == '采购计划']
    assert plan[0]['当前目录编号'] == 'IMG-NEW'
    assert plan[0]['状态'] == '已签约'
    contract = next(row for row in stage['rows'] if row.get('合同号') == 'HT-OLD')
    assert contract['合同原编号'] == 'IMG-OLD'
    assert contract['当前目录编号'] == 'IMG-NEW'
    assert client.post('/api/commit', json={'run_id': renamed['manifest']['run_id']}).get_json()['created'] == []


def test_commit_creates_contracts_with_current_plan_numbers(client):
    result = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    commit = client.post('/api/commit', json={'run_id': result['manifest']['run_id']}).get_json()
    assert [c['scene'] for c in commit['created']] == ['IMG-A', 'IMG-B']
    assert all(c['contract_no'].startswith('PC-') for c in commit['created'])
    stored = {c['contract_no']: c for c in contracts(client)}
    assert set(stored) == {c['contract_no'] for c in commit['created']}


def test_standalone_m8_uses_local_ledger(client):
    text = catalogue(['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'])
    run(client, text)
    client.post('/api/contracts', json={'contract_no': 'HT-A', 'scene': 'IMG-A', 'price': '40'})
    stage = client.post('/api/m8', json={'csv': text}).get_json()
    assert stage['rows'][0]['状态'] == '已签约'
    assert stage['contracts'][0]['contract_no'] == 'HT-A'


def test_reconciliation_csv_has_before_and_after_columns(client):
    run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    client.post('/api/contracts', json={'contract_no': 'HT-B', 'scene': 'IMG-B', 'price': '41'})
    merged = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', 'IMG-A', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    text = client.get('/api/reconciliation.csv?run_id=' + merged['manifest']['run_id']).data.decode('utf-8-sig')
    header = text.splitlines()[0]
    assert '合同原编号' in header and '当前目录编号' in header and '编号对照' in header
    row = next(r for r in csv.DictReader(io.StringIO(text)) if r['合同号'] == 'HT-B')
    assert row['合同原编号'] == 'IMG-B' and row['当前目录编号'] == 'IMG-A'
    assert row['对账目录修订'] == merged['manifest']['run_id']


def test_duplicate_marked_on_later_signing_date(client):
    run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', '', '172', '174', '', '', 'pass', '41', '2026-11-01T00:00:00Z', '1'],
    ))
    client.post('/api/contracts', json={'contracts': [
        {'contract_no': 'HT-LATE', 'scene': 'IMG-B', 'price': '41', 'signed_at': '2019-05-01'},
        {'contract_no': 'HT-EARLY', 'scene': 'IMG-A', 'price': '40', 'signed_at': '2018-05-01'},
    ]})
    merged = run(client, catalogue(
        ['IMG-A', '', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
        ['IMG-B', 'IMG-A', '170', '172', '', '', 'pass', '40', '2026-11-01T00:00:00Z', '1'],
    ))
    stage = m8(client, merged['manifest']['run_id'])
    by_no = {row['合同号']: row for row in stage['rows'] if row['种类'] == '已签合同'}
    assert by_no['HT-EARLY']['状态'] == '计划内'
    assert by_no['HT-LATE']['状态'] == '重复签约'
    assert stage['totals']['duplicate_cost'] == '41.0000'
