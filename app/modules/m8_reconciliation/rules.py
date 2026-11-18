from app.reconcile import build, rows


def apply(ctx, contracts=None, payments=None, active=None):
    reconciliation = build(ctx, contracts or [], payments or [], active or {'id': None, 'seq': None, 'digest': None, 'created_at': None, 'identity': ctx.get('identity', {})})
    ctx['reconciliation'] = reconciliation
    totals = reconciliation['totals']
    return {
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
    }
