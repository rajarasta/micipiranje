# biljeske-sync

Mali HTTP server za sync bilješki između uređaja. LWW per note, content-addressed privitci.

## API

| Method | Path | Body / Query | Purpose |
|---|---|---|---|
| `GET` | `/health` | — | liveness probe |
| `POST` | `/sync/push` | `{notes:[{id,updatedAt,deletedAt?,data}...]}` | upsert; vraća `accepted`/`rejected` po `updatedAt` |
| `GET` | `/sync/pull?since=<ms>` | — | sve bilješke s `updatedAt > since` |
| `PUT` | `/blobs/<sha256>` | raw bytes | content-addressed upload; provjerava sha |
| `GET` | `/blobs/<sha256>` | — | preuzmi blob |
| `HEAD` | `/blobs/<sha256>` | — | provjeri postoji li |

Sve osim `/health` traži `Authorization: Bearer <BILJESKE_TOKEN>`.

## Env

| Var | Default | Note |
|---|---|---|
| `BILJESKE_TOKEN` | — | **required**; shared bearer secret |
| `BILJESKE_DATA_DIR` | `./data` | sqlite + blobs |
| `BILJESKE_MAX_BLOB_BYTES` | `52428800` | per-blob limit (50 MB) |

## Local run

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
BILJESKE_TOKEN=$(openssl rand -hex 32) uvicorn server:app --port 8765
```

## Deploy to Fly.io (free tier)

```bash
# one-time
fly launch --copy-config --no-deploy        # accepts fly.toml as-is
fly volumes create biljeske_data --size 1   # 1 GB persistent disk
fly secrets set BILJESKE_TOKEN=$(openssl rand -hex 32)

# every deploy
fly deploy
```

After deploy, your server is at `https://biljeske-sync.fly.dev`. Read the token back later with `fly secrets list` (digest only) — store the token in a password manager when you generate it.

## Deploy anywhere else (Hetzner, Oracle, home box)

```bash
docker build -t biljeske-sync .
docker run -d --name biljeske-sync \
  -p 8080:8080 \
  -v $PWD/data:/data \
  -e BILJESKE_TOKEN=$(openssl rand -hex 32) \
  biljeske-sync
```

## Backup

Everything lives under `BILJESKE_DATA_DIR`:

```
data/
├── notes.db           SQLite — all notes (json blob per row)
├── notes.db-wal       WAL — copy too
├── notes.db-shm
└── blobs/<aa>/<sha>   content-addressed attachments
```

To back up: stop traffic briefly (or use `sqlite3 notes.db ".backup snapshot.db"`), then `tar czf backup.tgz data/`.
