"""Ingestion manifest: runs, source files and which companies each file was loaded for."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import duckdb

from engine.ingest.http import RemoteFile, RemoteMetadata


def start_run(conn: duckdb.DuckDBPyConnection, provider: str, dataset: str) -> UUID:
    return conn.execute(
        "INSERT INTO ingestion_runs (provider, dataset, started_at, status) "
        "VALUES (?, ?, ?, 'running') RETURNING id",
        [provider, dataset, datetime.now()],
    ).fetchone()[0]


def finish_run(conn: duckdb.DuckDBPyConnection, run_id: UUID, *, error: str | None = None) -> None:
    conn.execute(
        "UPDATE ingestion_runs SET finished_at = ?, status = ?, error = ? WHERE id = ?",
        [datetime.now(), "failed" if error else "success", error, run_id],
    )


def already_ingested(conn: duckdb.DuckDBPyConnection, remote: RemoteMetadata, cnpj: str) -> bool:
    """True when this exact file version was already loaded for the company."""
    if remote.etag is None and remote.last_modified is None:
        return False
    row = conn.execute(
        """
        SELECT count(*)
        FROM source_files AS sf
        JOIN source_file_scopes AS sc ON sc.source_file_id = sf.id
        JOIN ingestion_runs AS r ON r.id = sf.ingestion_run_id
        WHERE sf.url = ? AND sc.cnpj = ? AND r.status = 'success'
          AND (sf.etag = ? OR (? IS NULL AND sf.last_modified = ?))
        """,
        [remote.url, cnpj, remote.etag, remote.etag, remote.last_modified],
    ).fetchone()
    return bool(row and row[0])


def record_source_file(
    conn: duckdb.DuckDBPyConnection,
    run_id: UUID,
    remote: RemoteFile,
    *,
    rows_loaded: int,
    cnpjs: list[str],
) -> UUID:
    source_file_id = conn.execute(
        "INSERT INTO source_files (ingestion_run_id, url, retrieved_at, sha256, size_bytes, "
        "last_modified, rows_loaded, etag) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
        [
            run_id,
            remote.url,
            remote.retrieved_at,
            remote.sha256,
            remote.size_bytes,
            remote.last_modified,
            rows_loaded,
            remote.etag,
        ],
    ).fetchone()[0]
    if cnpjs:
        conn.executemany(
            "INSERT INTO source_file_scopes (source_file_id, cnpj) VALUES (?, ?)",
            [[source_file_id, cnpj] for cnpj in cnpjs],
        )
    return source_file_id
