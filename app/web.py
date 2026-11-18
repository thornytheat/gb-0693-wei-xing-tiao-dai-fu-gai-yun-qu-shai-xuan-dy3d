from flask import Blueprint, render_template, request
from app.config import TITLE, MODULES, SHORT, SAMPLE
from app.pipeline import calculate
from app.store import latest, save, get_run
from app import catalog
from app.ledger import present
bp=Blueprint('web',__name__)


def ensure_current():
    """Return the run for the active catalogue revision.

    The page shows whatever revision is active.  If a catalogue switch failed,
    the active flag still points at the previous revision, so the user keeps
    seeing the last good version instead of a half-applied one.
    """
    active=catalog.active()
    if active is not None:
        try: return present(get_run(active['id']))
        except Exception: pass
    run=latest()
    if run is not None: return present(run)
    result=calculate()
    catalog.activate(result)
    return save(result)


@bp.route('/')
@bp.route('/work/<int:stage>')
def work(stage=1):
    if stage<1 or stage>len(MODULES):
        from flask import abort
        abort(404)
    run=get_run(request.args['run_id']) if request.args.get('run_id') else ensure_current()
    if request.args.get('run_id'): run=present(run)
    current=run['stages'][str(stage)]
    return render_template('m'+str(stage)+'.html', title=TITLE, modules=MODULES, short=SHORT, run=run, current=current, stage=stage, sample=SAMPLE.read_text(encoding='utf-8-sig'), catalogue=catalog.active(), catalogues=catalog.history())
