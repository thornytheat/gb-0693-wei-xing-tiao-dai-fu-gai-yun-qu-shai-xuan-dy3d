"""Catalogue revisions and the identity map they imply.

Every successful run is a catalogue revision.  Revisions are append-only:
switching revisions only moves the ``active`` flag inside a single
transaction, so a failed switch leaves the previous revision active.
"""
import json

from app.db import connection
from app.errors import DomainError


def _payload(result):
    return {
        'identity': result.get('identity', {}),
        'sha256': result['manifest']['sha256'],
        'rule_version': result['manifest']['rule_version'],
        'scenes': len(result.get('scenes', [])),
    }


def record(result):
    """Store ``result`` as a revision without changing the active revision."""
    ident = result['manifest']['run_id']
    payload = _payload(result)
    with connection() as db:
        row = db.execute('SELECT id FROM catalogues WHERE id=?', (ident,)).fetchone()
        if row is None:
            seq = db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM catalogues').fetchone()[0]
            db.execute(
                'INSERT INTO catalogues(id,seq,digest,created_at,active,payload) VALUES(?,?,?,?,0,?)',
                (ident, seq, payload['sha256'], result['manifest']['created_at'], json.dumps(payload, ensure_ascii=False)),
            )
    return get(ident)


def activate(result):
    """Record ``result`` and make it the active catalogue revision."""
    ident = record(result)['id']
    switch(ident)
    return get(ident)


def switch(ident):
    """Activate an existing revision atomically.

    The UPDATE runs in one transaction.  If the revision does not exist the
    previous active revision is left untouched.
    """
    with connection() as db:
        row = db.execute('SELECT id FROM catalogues WHERE id=?', (ident,)).fetchone()
        if row is None:
            raise DomainError('CATALOGUE', '目录修订不存在，保留上一版', 404)
        db.execute('UPDATE catalogues SET active=0')
        db.execute('UPDATE catalogues SET active=1 WHERE id=?', (ident,))
    return get(ident)


def _read(row):
    payload = json.loads(row['payload'])
    return {
        'id': row['id'],
        'seq': row['seq'],
        'digest': row['digest'],
        'created_at': row['created_at'],
        'active': bool(row['active']),
        'identity': payload.get('identity', {}),
        'scenes': payload.get('scenes', 0),
        'rule_version': payload.get('rule_version'),
    }


def get(ident):
    with connection() as db:
        row = db.execute('SELECT id,seq,digest,created_at,active,payload FROM catalogues WHERE id=?', (ident,)).fetchone()
    return _read(row) if row else None


def active():
    with connection() as db:
        row = db.execute('SELECT id,seq,digest,created_at,active,payload FROM catalogues WHERE active=1 ORDER BY seq DESC LIMIT 1').fetchone()
    return _read(row) if row else None


def history():
    with connection() as db:
        rows = db.execute('SELECT id,seq,digest,created_at,active,payload FROM catalogues ORDER BY seq DESC').fetchall()
    return [_read(row) for row in rows]
