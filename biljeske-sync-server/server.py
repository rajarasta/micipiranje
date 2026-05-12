"""Biljeske sync server — single-user, last-write-wins, content-addressed blobs."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

DATA_DIR = Path(os.environ.get("BILJESKE_DATA_DIR", "./data")).resolve()
DB_PATH = DATA_DIR / "notes.db"
BLOBS_DIR = DATA_DIR / "blobs"
AUTH_TOKEN = os.environ.get("BILJESKE_TOKEN", "")
MAX_BLOB_BYTES = int(os.environ.get("BILJESKE_MAX_BLOB_BYTES", str(50 * 1024 * 1024)))

if not AUTH_TOKEN:
    raise RuntimeError("BILJESKE_TOKEN env var must be set")

DATA_DIR.mkdir(parents=True, exist_ok=True)
BLOBS_DIR.mkdir(parents=True, exist_ok=True)


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_schema() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                deleted_at INTEGER
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated_at)")


init_schema()


def require_auth(authorization: Annotated[str | None, Header()] = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    if authorization[7:] != AUTH_TOKEN:
        raise HTTPException(403, "Invalid token")


def blob_path(sha256: str) -> Path:
    return BLOBS_DIR / sha256[:2] / sha256


def server_time_ms() -> int:
    return int(time.time() * 1000)


class NoteIn(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    updatedAt: int = Field(ge=0)
    deletedAt: int | None = Field(default=None, ge=0)
    data: dict[str, Any]


class PushBody(BaseModel):
    notes: list[NoteIn]


app = FastAPI(title="biljeske-sync")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "PUT", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Content-Sha256"],
    expose_headers=["X-Server-Time"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "serverTime": server_time_ms()}


@app.post("/sync/push", dependencies=[Depends(require_auth)])
def sync_push(body: PushBody) -> dict[str, Any]:
    accepted: list[str] = []
    rejected: list[dict[str, Any]] = []
    with db() as conn:
        for note in body.notes:
            row = conn.execute(
                "SELECT updated_at FROM notes WHERE id = ?", (note.id,)
            ).fetchone()
            if row and row["updated_at"] >= note.updatedAt:
                rejected.append({"id": note.id, "reason": "stale", "serverUpdatedAt": row["updated_at"]})
                continue
            import json as _json

            conn.execute(
                """
                INSERT INTO notes (id, json, updated_at, deleted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    json = excluded.json,
                    updated_at = excluded.updated_at,
                    deleted_at = excluded.deleted_at
                """,
                (note.id, _json.dumps(note.data), note.updatedAt, note.deletedAt),
            )
            accepted.append(note.id)
    return {"accepted": accepted, "rejected": rejected, "serverTime": server_time_ms()}


@app.get("/sync/pull", dependencies=[Depends(require_auth)])
def sync_pull(since: int = 0) -> dict[str, Any]:
    import json as _json

    with db() as conn:
        rows = conn.execute(
            "SELECT id, json, updated_at, deleted_at FROM notes WHERE updated_at > ? ORDER BY updated_at",
            (since,),
        ).fetchall()
    notes = [
        {
            "id": r["id"],
            "updatedAt": r["updated_at"],
            "deletedAt": r["deleted_at"],
            "data": _json.loads(r["json"]),
        }
        for r in rows
    ]
    return {"notes": notes, "serverTime": server_time_ms()}


@app.head("/blobs/{sha256}", dependencies=[Depends(require_auth)])
def blob_head(sha256: str) -> Response:
    if not _valid_sha(sha256):
        raise HTTPException(400, "invalid sha256")
    p = blob_path(sha256)
    if not p.exists():
        raise HTTPException(404, "not found")
    return Response(status_code=200, headers={"Content-Length": str(p.stat().st_size)})


@app.get("/blobs/{sha256}", dependencies=[Depends(require_auth)])
def blob_get(sha256: str) -> Response:
    if not _valid_sha(sha256):
        raise HTTPException(400, "invalid sha256")
    p = blob_path(sha256)
    if not p.exists():
        raise HTTPException(404, "not found")
    return Response(content=p.read_bytes(), media_type="application/octet-stream")


@app.put("/blobs/{sha256}", dependencies=[Depends(require_auth)])
async def blob_put(sha256: str, request: Request) -> dict[str, Any]:
    if not _valid_sha(sha256):
        raise HTTPException(400, "invalid sha256")
    p = blob_path(sha256)
    if p.exists():
        return {"stored": False, "reason": "exists", "size": p.stat().st_size}
    body = await request.body()
    if len(body) > MAX_BLOB_BYTES:
        raise HTTPException(413, f"blob exceeds {MAX_BLOB_BYTES} bytes")
    actual = hashlib.sha256(body).hexdigest()
    if actual != sha256:
        raise HTTPException(400, f"sha mismatch: declared {sha256}, actual {actual}")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.rename(p)
    return {"stored": True, "size": len(body)}


def _valid_sha(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)
