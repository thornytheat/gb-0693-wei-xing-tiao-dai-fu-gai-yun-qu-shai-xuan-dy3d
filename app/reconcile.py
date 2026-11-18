"""Procurement reconciliation.

The plan always follows the *current* catalogue, so two scene numbers that a
revision merged become one candidate and cannot be bought twice.  Contracts
keep the scene number printed on them; reconciliation resolves that number
through the current identity map instead of rewriting it.  Each contract and
payment therefore stays traceable by its original number while the plan shows
the current number.
"""
from decimal import Decimal

from app.numeric import fmt


def _money(value):
    return fmt(value)


def _resolve(scene, identity):
    """Map an original scene number to the current canonical number."""
    return identity.get(scene)


def build(result, contracts, payments, active):
    # A batch is self-contained: its own identity map is the catalogue the
    # plan was computed against.  ``active`` only supplies catalogue metadata,
    # so re-activating another revision never rewrites a stored batch.
    identity = result.get('identity') or (active.get('identity') if active else {}) or {}
    paid_by_contract = {}
    for payment in payments:
        paid_by_contract[payment['contract_id']] = paid_by_contract.get(payment['contract_id'], Decimal(0)) + Decimal(payment['amount'])

    # Contracts grouped by the canonical scene they now denote.
    covered = {}
    for contract in contracts:
        canonical = _resolve(contract['scene'], identity)
        if canonical is not None:
            covered.setdefault(canonical, []).append(contract)

    plan = []
    for row in result.get('selected', []):
        canonical = row['canonical']
        matches = covered.get(canonical, [])
        entry = {
            'scene': canonical,
            'canonical': canonical,
            'price': str(Decimal(row['price_n'])),
            'gain': str(row['gain']),
            'status': '已签约' if matches else '新增采购',
            'contracts': [match['contract_no'] for match in matches],
            'contract_scenes': [match['scene'] for match in matches],
            'contract_count': len(matches),
            'duplicate': len(matches) > 1,
        }
        plan.append(entry)

    new_rows = [row for row in plan if row['status'] == '新增采购']
    signed_rows = [row for row in plan if row['status'] == '已签约']
    new_cost = sum((Decimal(row['price']) for row in new_rows), Decimal(0))
    avoided = sum((Decimal(row['price']) for row in signed_rows), Decimal(0))

    plan_by_scene = {row['scene']: row for row in plan}
    # For every image with several signed contracts, the earliest signed one is
    # treated as the legitimate purchase; later ones are duplicate commitments.
    surplus = set()
    duplicate_cost = Decimal(0)
    for canonical, matches in covered.items():
        if len(matches) > 1:
            # Prefer the date on the paper contract; fall back to ledger order.
            ordered = sorted(matches, key=lambda c: (c['signed_at'] or c['created_at'] or '', c['contract_no']))
            for extra in ordered[1:]:
                surplus.add(extra['contract_no'])
                duplicate_cost += Decimal(extra['price'])
    contract_rows = []
    for contract in contracts:
        canonical = _resolve(contract['scene'], identity)
        price = Decimal(contract['price'])
        paid = paid_by_contract.get(contract['id'], Decimal(0))
        if canonical is None:
            state = '目录未收录'
        elif canonical == contract['scene']:
            state = '目录保留原号'
        else:
            state = '目录已归并至 ' + canonical
        # More than one signed contract on the same image means the old
        # numbering caused a duplicate commitment; surface it, do not rewrite.
        duplicate = contract['contract_no'] in surplus
        contract_rows.append({
            'contract_no': contract['contract_no'],
            'scene_on_contract': contract['scene'],
            'scene_now': canonical or contract['scene'],
            'identity_state': state,
            'price': str(price),
            'paid': str(paid),
            'outstanding': str(price - paid),
            'in_plan': canonical in plan_by_scene,
            'duplicate': duplicate,
            'signed_at': contract['signed_at'],
            'catalogue_id': contract['catalogue_id'],
            'run_id': contract.get('run_id'),
        })

    payment_rows = []
    for payment in payments:
        contract = next((c for c in contracts if c['id'] == payment['contract_id']), None)
        if contract is None:
            continue
        payment_rows.append({
            'contract_no': contract['contract_no'],
            'scene_on_contract': contract['scene'],
            'scene_now': _resolve(contract['scene'], identity) or contract['scene'],
            'amount': str(Decimal(payment['amount'])),
            'paid_at': payment['paid_at'],
            'run_id': contract.get('run_id'),
            'catalogue_id': contract.get('catalogue_id'),
        })

    total_paid = sum((Decimal(p['amount']) for p in payments), Decimal(0))
    total_contract = sum((Decimal(c['price']) for c in contracts), Decimal(0))
    totals = {
        'plan_scenes': len(plan),
        'new_scenes': len(new_rows),
        'signed_scenes': len(signed_rows),
        'new_cost': _money(new_cost),
        'avoided_cost': _money(avoided),
        'contract_total': _money(total_contract),
        'paid_total': _money(total_paid),
        'outstanding_total': _money(total_contract - total_paid),
        'duplicate_cost': _money(duplicate_cost),
        'duplicate_scenes': len([1 for matches in covered.values() if len(matches) > 1]),
    }

    return {
        'catalogue': {
            'id': active['id'] if active else None,
            'seq': active['seq'] if active else None,
            'digest': active['digest'] if active else None,
            'created_at': active['created_at'] if active else None,
        },
        'plan': plan,
        'contracts': contract_rows,
        'payments': payment_rows,
        'totals': totals,
    }


EVIDENCE_FIELDS = ['种类', '序号', '当前目录编号', '合同原编号', '合同号', '编号对照', '状态', '价格_CNY', '新增覆盖_度', '已付_CNY', '未付_CNY', '付款时间', '来源批次', '目录修订']


def _uniform(row):
    """Pad a row to every evidence column, in a stable order.

    The page renders one header from the first row and then ``row.values()``,
    so every row must carry the same keys in the same order to stay aligned.
    """
    return {field: row.get(field, '') for field in EVIDENCE_FIELDS}


def rows(reconciliation):
    """Flatten reconciliation into uniform evidence rows."""
    answer = []
    for index, row in enumerate(reconciliation['plan'], start=1):
        answer.append(_uniform({
            '种类': '采购计划',
            '序号': index,
            '当前目录编号': row['scene'],
            '合同原编号': '、'.join(row['contract_scenes']) or '—',
            '状态': row['status'],
            '价格_CNY': row['price'],
            '新增覆盖_度': row['gain'],
        }))
    for index, row in enumerate(reconciliation['contracts'], start=1):
        answer.append(_uniform({
            '种类': '已签合同',
            '序号': index,
            '合同号': row['contract_no'],
            '当前目录编号': row['scene_now'],
            '合同原编号': row['scene_on_contract'],
            '编号对照': row['identity_state'],
            '状态': ('重复签约' if row['duplicate'] else ('计划内' if row['in_plan'] else '计划外')),
            '价格_CNY': row['price'],
            '已付_CNY': row['paid'],
            '未付_CNY': row['outstanding'],
            '来源批次': row.get('run_id') or '',
            '目录修订': row.get('catalogue_id') or '',
        }))
    for index, row in enumerate(reconciliation['payments'], start=1):
        answer.append(_uniform({
            '种类': '付款记录',
            '序号': index,
            '合同号': row['contract_no'],
            '当前目录编号': row['scene_now'],
            '合同原编号': row['scene_on_contract'],
            '已付_CNY': row['amount'],
            '付款时间': row['paid_at'],
        }))
    return answer
