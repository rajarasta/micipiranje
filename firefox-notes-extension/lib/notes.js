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
