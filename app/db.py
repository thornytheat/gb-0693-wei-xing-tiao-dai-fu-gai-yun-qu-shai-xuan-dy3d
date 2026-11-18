import os
import sqlite3
from pathlib import Path


def connection():
    """Open the local SQLite database and make sure every table exists."""
    path = Path(os.environ.get('APP_DB', 'data/runs.sqlite3'))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, decision TEXT NOT NULL DEFAULT "待复核")')
    # Immutable snapshots of every catalogue revision that was successfully
    # submitted.  A revision is never rewritten; only the active flag moves.
    db.execute('CREATE TABLE IF NOT EXISTS catalogues(id TEXT PRIMARY KEY, seq INTEGER NOT NULL, digest TEXT NOT NULL, created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0, payload TEXT NOT NULL)')
    # Signed contracts.  scene is the scene number written on the paper
    # contract and is never updated, even after a catalogue revision merges it
    # with another number.
    db.execute('CREATE TABLE IF NOT EXISTS contracts(id TEXT PRIMARY KEY, contract_no TEXT NOT NULL UNIQUE, scene TEXT NOT NULL, price TEXT NOT NULL, signed_at TEXT, catalogue_id TEXT, run_id TEXT, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
    # Append-only payment records referencing a contract.
    db.execute('CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY, contract_id TEXT NOT NULL, amount TEXT NOT NULL, paid_at TEXT, note TEXT, created_at TEXT NOT NULL)')
    # One commit per batch.  Retrying the same batch returns the stored
    # contract ids instead of inserting a second set.
    db.execute('CREATE TABLE IF NOT EXISTS commits(run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL)')
    return db
