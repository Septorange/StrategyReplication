"""Durable catalog for real experiment runs, evaluations, and saved schemes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ROOT

DB_PATH = ROOT / 'experiment_library.sqlite3'


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentLibrary:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _init_db(self):
        with self._connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    run_id TEXT PRIMARY KEY,
                    config_hash TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
                    snapshot_id TEXT NOT NULL,
                    from_date TEXT NOT NULL,
                    to_date TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS saved_experiments (
                    scheme_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES experiment_runs(run_id),
                    evaluation_id TEXT NOT NULL REFERENCES experiment_evaluations(evaluation_id),
                    name TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_saved_created ON saved_experiments(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_eval_run ON experiment_evaluations(run_id, created_at DESC);
            ''')

    def add_run(self, *, config_hash: str, snapshot_id: str, status: str, config: dict,
                artifact_path: Path, run_id: str | None = None) -> str:
        run_id = run_id or f'run_{uuid.uuid4().hex}'
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO experiment_runs VALUES (?,?,?,?,?,?,?)',
                       (run_id, config_hash, snapshot_id, status,
                        json.dumps(config, ensure_ascii=False, allow_nan=False), str(artifact_path), _now()))
            row=db.execute('SELECT config_hash,snapshot_id,status,config_json,artifact_path FROM experiment_runs WHERE run_id=?',(run_id,)).fetchone()
            expected=(config_hash,snapshot_id,status,json.dumps(config,ensure_ascii=False,allow_nan=False),str(artifact_path))
            if not row or tuple(row)!=expected:
                raise ValueError(f'Run identity collision or conflicting metadata for {run_id}.')
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute('SELECT * FROM experiment_runs WHERE run_id=?', (run_id,)).fetchone()
        if not row: return None
        result=dict(row);result['config']=json.loads(result.pop('config_json'))
        return result

    def add_evaluation(self, *, run_id: str, snapshot_id: str, from_date: str, to_date: str,
                       metrics: dict, evaluation_id: str | None = None) -> str:
        evaluation_id = evaluation_id or f'eval_{uuid.uuid4().hex}'
        with self._connect() as db:
            db.execute('INSERT OR IGNORE INTO experiment_evaluations VALUES (?,?,?,?,?,?,?)',
                       (evaluation_id, run_id, snapshot_id, from_date, to_date,
                        json.dumps(metrics, ensure_ascii=False, allow_nan=False), _now()))
            row=db.execute('SELECT run_id,snapshot_id,from_date,to_date,metrics_json FROM experiment_evaluations WHERE evaluation_id=?',(evaluation_id,)).fetchone()
            expected=(run_id,snapshot_id,from_date,to_date,json.dumps(metrics,ensure_ascii=False,allow_nan=False))
            if not row or tuple(row)!=expected:
                raise ValueError(f'Evaluation identity collision or conflicting metadata for {evaluation_id}.')
        return evaluation_id

    def save(self, *, run_id: str, evaluation_id: str, name: str, notes: str = '',
             scheme_id: str | None = None) -> dict[str, Any]:
        scheme_id = scheme_id or f'scheme_{uuid.uuid4().hex}'
        created_at = _now()
        with self._connect() as db:
            db.execute('INSERT INTO saved_experiments VALUES (?,?,?,?,?,?)',
                       (scheme_id, run_id, evaluation_id, name.strip(), notes.strip(), created_at))
        return {'scheme_id': scheme_id, 'run_id': run_id, 'evaluation_id': evaluation_id,
                'name': name.strip(), 'notes': notes.strip(), 'created_at': created_at}

    def list_saved(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute('''SELECT s.*, r.config_hash, r.snapshot_id, r.status, r.config_json,
                                       e.from_date, e.to_date, e.metrics_json
                                  FROM saved_experiments s
                                  JOIN experiment_runs r USING(run_id)
                                  JOIN experiment_evaluations e USING(evaluation_id)
                                 ORDER BY s.created_at DESC''').fetchall()
        return [self._saved_row(row) for row in rows]

    def get_saved(self, scheme_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute('''SELECT s.*, r.config_hash, r.snapshot_id, r.status, r.config_json,
                                       r.artifact_path, e.from_date, e.to_date, e.metrics_json
                                  FROM saved_experiments s
                                  JOIN experiment_runs r USING(run_id)
                                  JOIN experiment_evaluations e USING(evaluation_id)
                                 WHERE s.scheme_id=?''', (scheme_id,)).fetchone()
        if not row:
            return None
        result = self._saved_row(row)
        result['artifact_path'] = row['artifact_path']
        return result

    @staticmethod
    def _saved_row(row):
        result = dict(row)
        for source, target in [('config_json', 'config'), ('metrics_json', 'metrics')]:
            if source in result:
                result[target] = json.loads(result.pop(source))
        return result


def resolve_artifact(library: ExperimentLibrary, saved: dict) -> dict[str, Any]:
    path = Path(saved['artifact_path']).resolve()
    cache_root = (ROOT / 'experiment_cache').resolve()
    if not path.is_relative_to(cache_root) or not path.is_dir():
        raise FileNotFoundError('Saved experiment artifacts are missing or outside the local cache.')
    result_path = path / 'result.json'
    if not result_path.is_file():
        raise FileNotFoundError('Saved experiment result.json is missing.')
    manifest_path=path/'artifact_manifest.json'
    if not manifest_path.is_file():
        raise FileNotFoundError('Saved experiment artifact manifest is missing.')
    result = json.loads(result_path.read_text())
    manifest=json.loads(manifest_path.read_text())
    if result.get('status') != 'PASS' or result.get('synthetic') is not False:
        raise ValueError('Saved scheme is not a completed real Python experiment.')
    expected_hash=saved.get('config_hash')
    expected_snapshot=saved.get('snapshot_id')
    expected_config=saved.get('config')
    identity=result.get('identity_sha256')
    if not isinstance(identity,str) or len(identity)!=64 or expected_hash!=identity or result.get('config_hash')!=identity:
        raise ValueError('Saved artifact identity does not match its full SHA-256 SQLite run record.')
    if result.get('snapshot_id')!=expected_snapshot:
        raise ValueError('Saved artifact snapshot does not match its SQLite run record.')
    result_sha256=hashlib.sha256(result_path.read_bytes()).hexdigest()
    if (manifest.get('result_sha256')!=result_sha256
            or manifest.get('identity_sha256')!=identity
            or manifest.get('config_hash')!=identity
            or manifest.get('snapshot_id')!=expected_snapshot
            or manifest.get('cache_key')!=identity[:16]
            or manifest.get('adapter_version')!=4
            or result.get('adapter_version')!=4):
        raise ValueError('Saved artifact manifest, result digest, or adapter version is invalid.')
    if saved.get('run_id')!=f'run_{identity}' or path.name!=result.get('cache_key') or path.name!=identity[:16]:
        raise ValueError('Saved artifact run ID or cache key does not match its identity.')
    if expected_config is not None and expected_config!=result.get('config'):
        raise ValueError('Saved artifact config does not match its SQLite run record.')
    source_hashes=result.get('source_hashes')
    if not isinstance(source_hashes,dict) or result.get('baseline') is None:
        raise ValueError('Saved artifact is missing identity source metadata.')
    identity_payload={'config':result.get('config'),'snapshot_id':result.get('snapshot_id'),
        'source_hashes':source_hashes,'baseline':result.get('baseline'),'adapter_version':4}
    recomputed=hashlib.sha256(json.dumps(identity_payload,sort_keys=True).encode()).hexdigest()
    if recomputed!=identity:
        raise ValueError('Saved artifact full identity digest is invalid.')
    return result
