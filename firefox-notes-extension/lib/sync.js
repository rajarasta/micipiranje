const CONFIG_KEY = 'sync';

let syncInFlight = null;

export async function getSyncConfig(db) {
  const rec = await new Promise((resolve, reject) => {
    const tx = db.transaction('config', 'readonly');
    const req = tx.objectStore('config').get(CONFIG_KEY);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return rec ? rec.value : null;
}

export async function setSyncConfig(db, cfg) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction('config', 'readwrite');
    tx.objectStore('config').put({ key: CONFIG_KEY, value: cfg });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

export function isConfigured(cfg) {
  return !!(cfg && cfg.serverUrl && cfg.token);
}

async function sha256Hex(blob) {
  const buf = await blob.arrayBuffer();
  const hash = await crypto.subtle.digest('SHA-256', buf);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}

function authHeaders(cfg, extra = {}) {
  return { 'Authorization': `Bearer ${cfg.token}`, ...extra };
}

function joinUrl(base, path) {
  return base.replace(/\/+$/, '') + path;
}

export async function pingServer(cfg) {
  const res = await fetch(joinUrl(cfg.serverUrl, '/health'), {
    method: 'GET',
    cache: 'no-store'
  });
  if (!res.ok) return { ok: false, status: res.status };
  const json = await res.json();
  return { ok: true, serverTime: json.serverTime };
}

export async function checkAuth(cfg) {
  const res = await fetch(joinUrl(cfg.serverUrl, '/sync/pull?since=99999999999999'), {
    headers: authHeaders(cfg)
  });
  return { ok: res.ok, status: res.status };
}

async function blobExists(cfg, sha) {
  const res = await fetch(joinUrl(cfg.serverUrl, `/blobs/${sha}`), {
    method: 'HEAD',
    headers: authHeaders(cfg)
  });
  return res.ok;
}

async function uploadBlob(cfg, sha, blob, mimeType) {
  if (await blobExists(cfg, sha)) return false;
  const res = await fetch(joinUrl(cfg.serverUrl, `/blobs/${sha}`), {
    method: 'PUT',
    headers: authHeaders(cfg, { 'Content-Type': mimeType || 'application/octet-stream' }),
    body: blob
  });
  if (!res.ok) throw new Error(`blob upload ${sha}: ${res.status}`);
  return true;
}

async function downloadBlob(cfg, sha) {
  const res = await fetch(joinUrl(cfg.serverUrl, `/blobs/${sha}`), {
    headers: authHeaders(cfg)
  });
  if (!res.ok) throw new Error(`blob download ${sha}: ${res.status}`);
  return res.blob();
}

function getRec(db, storeName, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const r = tx.objectStore(storeName).get(id);
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

function putRec(db, storeName, record) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).put(record);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function getAll(db, storeName) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const r = tx.objectStore(storeName).getAll();
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

async function ensureLocalAttachmentSha(db, attId) {
  const att = await getRec(db, 'attachments', attId);
  if (!att) return null;
  if (att.sha256) return att;
  att.sha256 = await sha256Hex(att.blob);
  await putRec(db, 'attachments', att);
  return att;
}

async function ensureRemoteAttachment(db, cfg, attId) {
  const att = await ensureLocalAttachmentSha(db, attId);
  if (!att) return null;
  await uploadBlob(cfg, att.sha256, att.blob, att.mimeType);
  return att;
}

async function importRemoteAttachment(db, cfg, attMeta) {
  const existing = await getRec(db, 'attachments', attMeta.id);
  if (existing) {
    if (!existing.sha256 && attMeta.sha256) {
      existing.sha256 = attMeta.sha256;
      await putRec(db, 'attachments', existing);
    }
    return existing;
  }
  const blob = await downloadBlob(cfg, attMeta.sha256);
  const att = {
    id: attMeta.id,
    blob,
    mimeType: attMeta.mimeType || blob.type || '',
    filename: attMeta.filename || '',
    size: attMeta.size || blob.size,
    sha256: attMeta.sha256,
    thumbBlob: null
  };
  await putRec(db, 'attachments', att);
  return att;
}

function serializeNoteForPush(note, attachments) {
  return {
    id: note.id,
    updatedAt: note.updatedAt,
    deletedAt: note.deletedAt || null,
    data: {
      title: note.title || '',
      body: note.body || '',
      attachments,
      pinned: !!note.pinned,
      tags: note.tags || [],
      createdAt: note.createdAt || note.updatedAt
    }
  };
}

function deserializeRemoteNote(remote) {
  const data = remote.data || {};
  const atts = data.attachments || [];
  return {
    id: remote.id,
    title: data.title || '',
    body: data.body || '',
    attachmentIds: atts.map(a => a.id),
    pinned: !!data.pinned,
    tags: Array.isArray(data.tags) ? data.tags : [],
    createdAt: data.createdAt || remote.updatedAt,
    updatedAt: remote.updatedAt,
    ...(remote.deletedAt ? { deletedAt: remote.deletedAt } : {})
  };
}

async function pullChanges(db, cfg) {
  const since = cfg.lastPulledAt || 0;
  const res = await fetch(joinUrl(cfg.serverUrl, `/sync/pull?since=${since}`), {
    headers: authHeaders(cfg)
  });
  if (!res.ok) throw new Error(`pull: ${res.status}`);
  const data = await res.json();

  let merged = 0;
  for (const remote of data.notes) {
    const local = await getRec(db, 'notes', remote.id);
    if (local && local.updatedAt >= remote.updatedAt) continue;

    const remoteAtts = (remote.data && remote.data.attachments) || [];
    for (const ref of remoteAtts) {
      try {
        await importRemoteAttachment(db, cfg, ref);
      } catch (err) {
        console.warn('[sync] attachment import failed', ref.id, err);
      }
    }
    await putRec(db, 'notes', deserializeRemoteNote(remote));
    merged++;
  }

  return { pulledFrom: since, merged, serverTime: data.serverTime };
}

async function pushChanges(db, cfg, pulledServerTime) {
  const allLocal = await getAll(db, 'notes');
  const since = cfg.lastPushedAt || 0;
  const dirty = allLocal.filter(n => (n.updatedAt || 0) > since);

  // Upload missing blobs first
  for (const note of dirty) {
    for (const attId of note.attachmentIds || []) {
      try {
        await ensureRemoteAttachment(db, cfg, attId);
      } catch (err) {
        console.warn('[sync] blob upload failed', attId, err);
      }
    }
  }

  const pushNotes = [];
  for (const note of dirty) {
    const attMeta = [];
    for (const attId of note.attachmentIds || []) {
      const att = await getRec(db, 'attachments', attId);
      if (att && att.sha256) {
        attMeta.push({
          id: att.id,
          sha256: att.sha256,
          mimeType: att.mimeType,
          filename: att.filename,
          size: att.size
        });
      }
    }
    pushNotes.push(serializeNoteForPush(note, attMeta));
  }

  if (pushNotes.length === 0) {
    return { pushed: 0, rejected: 0, serverTime: pulledServerTime };
  }

  const res = await fetch(joinUrl(cfg.serverUrl, '/sync/push'), {
    method: 'POST',
    headers: authHeaders(cfg, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ notes: pushNotes })
  });
  if (!res.ok) throw new Error(`push: ${res.status}`);
  const data = await res.json();
  return {
    pushed: data.accepted.length,
    rejected: data.rejected.length,
    serverTime: data.serverTime
  };
}

export async function runSync(db) {
  if (syncInFlight) return syncInFlight;
  syncInFlight = (async () => {
    const cfg = await getSyncConfig(db);
    if (!isConfigured(cfg)) return { ok: false, reason: 'not-configured' };
    try {
      const pull = await pullChanges(db, cfg);
      const push = await pushChanges(db, cfg, pull.serverTime);
      await setSyncConfig(db, {
        ...cfg,
        lastPulledAt: pull.serverTime,
        lastPushedAt: push.serverTime,
        lastSyncResult: {
          at: Date.now(),
          pulled: pull.merged,
          pushed: push.pushed,
          rejected: push.rejected
        }
      });
      return {
        ok: true,
        pulled: pull.merged,
        pushed: push.pushed,
        rejected: push.rejected
      };
    } catch (err) {
      const cfg2 = await getSyncConfig(db);
      await setSyncConfig(db, {
        ...(cfg2 || cfg),
        lastSyncError: { at: Date.now(), message: String(err && err.message || err) }
      });
      throw err;
    }
  })();
  try {
    return await syncInFlight;
  } finally {
    syncInFlight = null;
  }
}
