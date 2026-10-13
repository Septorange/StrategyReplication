"""Durable catalog for real experiment runs, evaluations, and saved schemes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import pyarrow.parquet as pq

from .config import ROOT
from .experiment_runner import REQUIRED_PARQUET_COLUMNS

DB_PATH = ROOT / 'experiment_library.sqlite3'

REQUIRED_ARTIFACTS = {
    'daily_portfolio.parquet', 'single_asset_vol_control.parquet',
    'final_daily_weights.parquet', 'events.parquet',
    'experiment_trade_returns.parquet', 'engine_run.json',
}


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
            cols={row[1] for row in db.execute('PRAGMA table_info(saved_experiments)')}
            if 'tags_json' not in cols: db.execute("ALTER TABLE saved_experiments ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
            if 'updated_at' not in cols: db.execute("ALTER TABLE saved_experiments ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")
            if 'deleted_at' not in cols: db.execute("ALTER TABLE saved_experiments ADD COLUMN deleted_at TEXT")

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

    def save(self, *, run_id: str, evaluation_id: str, name: str, notes: str = '', tags: list[str] | None = None,
             scheme_id: str | None = None) -> dict[str, Any]:
        scheme_id = scheme_id or f'scheme_{uuid.uuid4().hex}'
        created_at = _now()
        tags=tags or []
        with self._connect() as db:
            db.execute('''INSERT INTO saved_experiments
                (scheme_id,run_id,evaluation_id,name,notes,created_at,tags_json,updated_at)
                VALUES (?,?,?,?,?,?,?,?)''',
                       (scheme_id, run_id, evaluation_id, name.strip(), notes.strip(), created_at,
                        json.dumps(tags,ensure_ascii=False),created_at))
        return {'scheme_id': scheme_id, 'run_id': run_id, 'evaluation_id': evaluation_id,
                'name': name.strip(), 'notes': notes.strip(), 'tags': tags,
                'created_at': created_at, 'updated_at': created_at}

    def list_saved(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute('''SELECT s.*, r.config_hash, r.snapshot_id, r.status, r.config_json, r.artifact_path,
                                       e.from_date, e.to_date, e.metrics_json
                                  FROM saved_experiments s
                                  JOIN experiment_runs r USING(run_id)
                                  JOIN experiment_evaluations e USING(evaluation_id)
                                 WHERE s.deleted_at IS NULL
                                 ORDER BY s.created_at DESC''').fetchall()
        items=[]
        for row in rows:
            item=self._saved_row(row)
            path=Path(row['artifact_path'])
            manifest=path/'artifact_manifest.json'
            manifest_data = None
            if manifest.is_file():
                try:
                    manifest_data = json.loads(manifest.read_text())
                except (OSError, json.JSONDecodeError):
                    manifest_data = None
            stage_digests = manifest_data.get('artifact_sha256') if isinstance(manifest_data, dict) else None
            certified = (isinstance(stage_digests, dict)
                         and REQUIRED_ARTIFACTS.issubset(stage_digests)
                         and all((path / name).is_file() for name in REQUIRED_ARTIFACTS))
            if item.get('status') == 'PASS' and not certified:
                item['status']='LEGACY_UNVERIFIED'
                item['integrity_note']='旧实验产物缺少完整 Phase 2 artifact manifest 或阶段文件，不能自动复用或比较。'
            items.append(item)
        return items

    def get_saved(self, scheme_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute('''SELECT s.*, r.config_hash, r.snapshot_id, r.status, r.config_json,
                                       r.artifact_path, e.from_date, e.to_date, e.metrics_json
                                  FROM saved_experiments s
                                  JOIN experiment_runs r USING(run_id)
                                  JOIN experiment_evaluations e USING(evaluation_id)
                                 WHERE s.scheme_id=? AND s.deleted_at IS NULL''', (scheme_id,)).fetchone()
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
        result['tags']=json.loads(result.pop('tags_json','[]') or '[]')
        return result

    def update_saved(self, scheme_id: str, *, name: str|None=None, notes: str|None=None,
                     tags: list[str]|None=None) -> dict[str, Any] | None:
        now=_now()
        fields=[]; values=[]
        if name is not None: fields.append('name=?'); values.append(name.strip())
        if notes is not None: fields.append('notes=?'); values.append(notes.strip())
        if tags is not None: fields.append('tags_json=?'); values.append(json.dumps(tags,ensure_ascii=False))
        if not fields: return self.get_saved(scheme_id)
        fields.append('updated_at=?'); values.append(now); values.append(scheme_id)
        with self._connect() as db:
            db.execute(f"UPDATE saved_experiments SET {', '.join(fields)} WHERE scheme_id=? AND deleted_at IS NULL",values)
        return self.get_saved(scheme_id)

    def delete_saved(self, scheme_id: str) -> bool:
        with self._connect() as db:
            cur=db.execute('UPDATE saved_experiments SET deleted_at=?, updated_at=? WHERE scheme_id=? AND deleted_at IS NULL',(_now(),_now(),scheme_id))
        return cur.rowcount > 0


def resolve_artifact(library: ExperimentLibrary, saved: dict) -> dict[str, Any]:
    raw_path = Path(saved['artifact_path'])
    if raw_path.is_symlink():
        raise FileNotFoundError('Saved experiment artifact directory is a symlink.')
    path = raw_path.resolve()
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
    invalid=[]
    for name in REQUIRED_ARTIFACTS:
        candidate=path/name
        resolved=candidate.resolve()
        if (candidate.is_symlink() or not resolved.is_relative_to(path)
                or not candidate.is_file() or candidate.stat().st_size <= 0):
            invalid.append(name); continue
        if name.endswith('.parquet'):
            try:
                parquet=pq.ParquetFile(candidate)
                required=REQUIRED_PARQUET_COLUMNS[name]
                invalid_schema=(parquet.metadata is None or parquet.metadata.num_rows <= 0
                                or not required.issubset(set(parquet.schema.names)))
            except Exception:
                invalid_schema=True
            if invalid_schema:
                invalid.append(name)
        elif name=='engine_run.json':
            try:
                if not isinstance(json.loads(candidate.read_text()),dict): invalid.append(name)
            except (OSError,ValueError,TypeError): invalid.append(name)
    if invalid:
        raise FileNotFoundError('Saved experiment stage artifacts are invalid: ' + ', '.join(sorted(invalid)))
    artifact_hashes = manifest.get('artifact_sha256')
    if not isinstance(artifact_hashes, dict):
        raise ValueError('Saved artifact manifest lacks stage file digests; legacy artifact is not certified.')
    for name in REQUIRED_ARTIFACTS:
        digest = artifact_hashes.get(name)
        if not isinstance(digest, str) or hashlib.sha256((path / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Saved experiment stage artifact digest is invalid: {name}')
    return result
