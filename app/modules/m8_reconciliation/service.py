from collections import Counter

from app.modules.m8_reconciliation.rules import apply
from app.numeric import serial


def execute(ctx):
    before = len(ctx['quarantine'])
    # Stage 8 is pure: it reconciles the batch against whatever ledger rows are
    # supplied on the context.  The API and pages overlay the live local ledger
    # via ``ledger.present`` so a stored batch stays reproducible.
    result = apply(ctx, ctx.get('ledger_contracts', []), ctx.get('ledger_payments', []), {
        'id': ctx['manifest']['run_id'],
        'seq': None,
        'digest': ctx['manifest']['sha256'],
        'created_at': ctx['manifest']['created_at'],
        'identity': ctx.get('identity', {}),
    })
    result['stage'] = 8
    result['name'] = '采购对账'
    result['issues'] = dict(Counter(row['原因码'] for row in ctx['quarantine']))
    result['new_quarantine'] = len(ctx['quarantine']) - before
    ctx['stages'][str(8)] = serial(result)
    return ctx
