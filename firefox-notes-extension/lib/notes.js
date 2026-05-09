import { put, get, listByIndex, runTx } from './db.js';

export async function createNote(db) {
  const now = Date.now();
  const note = {
    id: crypto.randomUUID(),
    title: '',
    body: '',
    attachmentIds: [],
    createdAt: now,
    updatedAt: now
  };
  await put(db, 'notes', note);
  return note;
}

export function getNote(db, id) {
  return get(db, 'notes', id);
}

export function listNotes(db) {
  return listByIndex(db, 'notes', 'updatedAt', 'prev');
}

const ALLOWED_UPDATE_FIELDS = ['title', 'body'];

export async function updateNote(db, id, patch) {
  const existing = await getNote(db, id);
  if (!existing) throw new Error(`Note not found: ${id}`);

  const filteredPatch = {};
  for (const key of ALLOWED_UPDATE_FIELDS) {
    if (key in patch) filteredPatch[key] = patch[key];
  }

  const updated = {
    ...existing,
    ...filteredPatch,
    updatedAt: Date.now()
  };
  await put(db, 'notes', updated);
  return updated;
}

export function getAttachment(db, id) {
  return get(db, 'attachments', id);
}

export async function addAttachment(db, noteId, blob, mimeType, filename) {
  const note = await getNote(db, noteId);
  if (!note) throw new Error(`Note not found: ${noteId}`);

  const att = {
    id: crypto.randomUUID(),
    blob,
    mimeType,
    filename,
    size: blob.size
  };

  await runTx(db, ['notes', 'attachments'], 'readwrite', (tx) => {
    tx.objectStore('attachments').put(att);
    tx.objectStore('notes').put({
      ...note,
      attachmentIds: [...note.attachmentIds, att.id],
      updatedAt: Date.now()
    });
  });

  return att;
}

export async function removeAttachment(db, noteId, attachmentId) {
  const note = await getNote(db, noteId);
  if (!note || !note.attachmentIds.includes(attachmentId)) return;

  await runTx(db, ['notes', 'attachments'], 'readwrite', (tx) => {
    tx.objectStore('attachments').delete(attachmentId);
    tx.objectStore('notes').put({
      ...note,
      attachmentIds: note.attachmentIds.filter(id => id !== attachmentId),
      updatedAt: Date.now()
    });
  });
}

export async function deleteNote(db, id) {
  const note = await getNote(db, id);
  if (!note) return;

  await runTx(db, ['notes', 'attachments'], 'readwrite', (tx) => {
    const attStore = tx.objectStore('attachments');
    for (const attId of note.attachmentIds) {
      attStore.delete(attId);
    }
    tx.objectStore('notes').delete(id);
  });
}

export async function searchNotes(db, query) {
  const all = await listNotes(db);
  if (!query) return all;
  const needle = query.toLowerCase();
  return all.filter(n =>
    n.title.toLowerCase().includes(needle) ||
    n.body.toLowerCase().includes(needle)
  );
}
