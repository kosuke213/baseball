"""Small HTTPS collector. No credentials, TLS overrides, or implicit bulk crawl."""
from __future__ import annotations

import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class CollectionError(Exception):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        f.write(text.encode("utf-8"))
    os.replace(tmp, path)


def safe_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise CollectionError("Only HTTPS URLs without credentials/fragments are supported")
    return parts.hostname


class Redirects(HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = set(allowed)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if safe_url(newurl) not in self.allowed:
            raise CollectionError("Redirect destination is outside the artifact host allowlist")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Collector:
    def __init__(self, root: Path, rights: dict, *, offline=False, budget=64_000_000):
        self.root, self.rights, self.offline = root, rights, offline
        self.remaining = budget
        self.last_request = {}
        self.network_requests = 0
        self.cache_hits = 0

    def fetch(self, spec: dict) -> tuple[bytes, dict]:
        artifact_id = spec["id"]
        if not re.fullmatch(r"[a-z0-9_-]+", artifact_id):
            raise CollectionError("Invalid artifact ID")
        rights = self.rights[spec["rights"]]
        if spec["purpose"] == "data" and not rights["pilot_collection_allowed"]:
            raise CollectionError("Data collection is deferred pending rights review")
        host = safe_url(spec["url"])
        fingerprint = digest(json.dumps({k: v for k, v in spec.items() if k != "expected_sha256"}, sort_keys=True).encode())
        index = self.root / "index" / (artifact_id + ".json")
        if index.exists():
            meta = json.loads(index.read_text())
            if meta["request_fingerprint"] != fingerprint:
                raise CollectionError("Artifact specification changed: use a new artifact ID")
            sha = meta["sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise CollectionError("Invalid cached digest")
            blob = self.root / "blobs" / sha
            if not blob.exists() or blob.stat().st_size > spec["max_bytes"]:
                raise CollectionError("Cached artifact is missing or exceeds the size limit")
            data = blob.read_bytes()
            if digest(data) != sha or len(data) != meta["bytes"]:
                raise CollectionError("Cached artifact checksum/length mismatch")
            if spec.get("expected_sha256") and sha != spec["expected_sha256"]:
                raise CollectionError("Cached artifact differs from the pinned checksum")
            self.cache_hits += 1
            return data, meta
        if self.offline:
            raise CollectionError("Artifact is unavailable in offline cache")
        allowed = [host, *spec.get("redirect_hosts", [])]
        opener = build_opener(Redirects(allowed))
        for attempt in range(3):
            time.sleep(max(0, self.last_request.get(host, 0) + 0.4 - time.monotonic()))
            self.last_request[host] = time.monotonic()
            req = Request(spec["url"], headers={
                "User-Agent": "BaseballDataPilot/0.1 (bounded research sample)",
                "Accept-Encoding": "identity",
            })
            self.network_requests += 1
            try:
                with opener.open(req, timeout=30) as response:
                    if response.status != 200:
                        raise CollectionError(f"Unexpected HTTP {response.status}")
                    if safe_url(response.url) not in allowed:
                        raise CollectionError("Unexpected final host")
                    limit = min(spec["max_bytes"], self.remaining)
                    size = int(response.headers.get("Content-Length", "0"))
                    if size > limit:
                        raise CollectionError("Artifact exceeds the byte budget")
                    chunks, n = [], 0
                    deadline = time.monotonic() + 120
                    while chunk := response.read(min(65536, limit - n + 1)):
                        n += len(chunk)
                        self.remaining -= len(chunk)
                        if n > limit or time.monotonic() > deadline:
                            raise CollectionError("Artifact exceeds size/time budget")
                        chunks.append(chunk)
                    data = b"".join(chunks)
                    if not data or (size and size != len(data)):
                        raise CollectionError("Empty or truncated HTTP payload")
                    sha = digest(data)
                    if spec.get("expected_sha256") and sha != spec["expected_sha256"]:
                        raise CollectionError("Upstream content differs from the pinned checksum")
                    meta = {
                        **spec, "request_fingerprint": fingerprint, "sha256": sha,
                        "bytes": len(data), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                        "final_url": response.url, "http_status": response.status,
                        "content_type": response.headers.get("Content-Type"),
                        "etag": response.headers.get("ETag"),
                        "last_modified": response.headers.get("Last-Modified"),
                        "rights_snapshot": rights,
                    }
                blob = self.root / "blobs" / sha
                blob.parent.mkdir(parents=True, exist_ok=True)
                if blob.exists() and digest(blob.read_bytes()) != sha:
                    raise CollectionError("Existing content-addressed blob is corrupt")
                if not blob.exists():
                    # Publish only a completely downloaded, verified object.
                    with tempfile.NamedTemporaryFile(dir=blob.parent, delete=False) as f:
                        tmp = Path(f.name)
                        f.write(data)
                    os.replace(tmp, blob)
                write_json(index, meta)
                return data, meta
            except HTTPError as exc:
                status, retry = exc.code, exc.headers.get("Retry-After", "")
                exc.close()
                if status in (429, 500, 502, 503, 504) and attempt < 2:
                    # Long provider cooldowns stop this run; never retry 401/403.
                    delay = int(retry) if retry.isdigit() else 2 ** attempt
                    if delay > 30 or (retry and not retry.isdigit()):
                        raise CollectionError(f"HTTP {status}; provider cooldown requires a later run") from None
                    time.sleep(delay)
                    continue
                raise CollectionError(f"HTTP {status}") from None
            except (URLError, TimeoutError, OSError, ValueError, HTTPException):
                # Exception strings can contain proxy addresses or credentials.
                raise CollectionError("Network/TLS/transport failure; no data accepted") from None
        raise CollectionError("Retry limit reached")
