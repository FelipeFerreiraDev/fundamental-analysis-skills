"""Downloading public files with a short-lived local cache.

Files are kept in data/cache/ only long enough to avoid downloading the same file twice in a
short period (e.g. when a peer company is added in the same week). They are not an archive:
traceability comes from the manifest (URL, ETag, SHA-256) stored in the warehouse.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

from engine import __version__

CACHE_TTL_SECONDS = 7 * 24 * 3600
USER_AGENT = f"skillsinvest/{__version__}"


@dataclass(frozen=True)
class RemoteMetadata:
    url: str
    etag: str | None
    last_modified: datetime | None


@dataclass(frozen=True)
class RemoteFile:
    url: str
    path: Path
    sha256: str
    size_bytes: int
    etag: str | None
    last_modified: datetime | None
    retrieved_at: datetime


class Fetcher(Protocol):
    def metadata(self, url: str) -> RemoteMetadata | None:
        """ETag / Last-Modified of a URL, or None when it does not exist."""

    def fetch(self, url: str) -> RemoteFile:
        """Local copy of the URL (from cache when the remote file did not change)."""

    def download(self, url: str, headers: dict[str, str] | None = None) -> RemoteFile:
        """Fresh copy of an API response (no HEAD, no reuse). Headers never reach the manifest."""


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    return parsedate_to_datetime(value).astimezone(UTC).replace(tzinfo=None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HttpFetcher:
    def __init__(self, cache_dir: Path, *, timeout: int = 300) -> None:
        self.cache_dir = cache_dir
        self.timeout = timeout

    def _request(self, url: str, method: str) -> urllib.request.Request:
        return urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})

    def metadata(self, url: str) -> RemoteMetadata | None:
        try:
            with urllib.request.urlopen(self._request(url, "HEAD"), timeout=self.timeout) as resp:
                return RemoteMetadata(
                    url=url,
                    etag=resp.headers.get("ETag"),
                    last_modified=_parse_http_date(resp.headers.get("Last-Modified")),
                )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def fetch(self, url: str) -> RemoteFile:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}-{url.rsplit('/', 1)[-1].split('?')[0]}"
        meta_path = path.with_suffix(path.suffix + ".json")
        remote = self.metadata(url)
        if remote is None:
            raise FileNotFoundError(url)

        if path.exists() and meta_path.exists():
            cached = json.loads(meta_path.read_text(encoding="utf-8"))
            if remote.etag is not None and cached.get("etag") == remote.etag:
                return self._describe(url, path, cached, remote)

        tmp = path.with_suffix(path.suffix + ".part")
        request = self._request(url, "GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as resp, tmp.open("wb") as fh:
            shutil.copyfileobj(resp, fh, length=1 << 20)
        tmp.replace(path)
        cached = {"etag": remote.etag, "retrieved_at": datetime.now(UTC).isoformat()}
        meta_path.write_text(json.dumps(cached), encoding="utf-8")
        return self._describe(url, path, cached, remote)

    def download(self, url: str, headers: dict[str, str] | None = None) -> RemoteFile:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        retrieved_at = datetime.now(UTC)
        key = hashlib.sha256(url.encode()).hexdigest()[:16]
        path = self.cache_dir / f"{key}-{retrieved_at:%Y%m%dT%H%M%S%f}.json"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            path.write_bytes(resp.read())
            etag = resp.headers.get("ETag")
            last_modified = _parse_http_date(resp.headers.get("Last-Modified"))
        return RemoteFile(
            url=url,
            path=path,
            sha256=_sha256(path),
            size_bytes=path.stat().st_size,
            etag=etag,
            last_modified=last_modified,
            retrieved_at=retrieved_at.replace(tzinfo=None),
        )

    def _describe(self, url: str, path: Path, cached: dict, remote: RemoteMetadata) -> RemoteFile:
        return RemoteFile(
            url=url,
            path=path,
            sha256=_sha256(path),
            size_bytes=path.stat().st_size,
            etag=remote.etag,
            last_modified=remote.last_modified,
            retrieved_at=datetime.fromisoformat(cached["retrieved_at"]).replace(tzinfo=None),
        )


def purge_expired_cache(cache_dir: Path, ttl_seconds: int = CACHE_TTL_SECONDS) -> int:
    """Delete cached downloads older than the TTL. Returns how many files were removed."""
    if not cache_dir.exists():
        return 0
    limit = time.time() - ttl_seconds
    removed = 0
    for path in cache_dir.rglob("*"):
        if path.is_file() and path.stat().st_mtime < limit:
            path.unlink()
            removed += 1
    return removed
