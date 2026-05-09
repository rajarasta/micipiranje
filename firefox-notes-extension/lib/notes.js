import { put, get, listByIndex } from './db.js';

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
