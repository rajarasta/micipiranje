import { openDb, DB_NAME } from '../lib/db.js';
import { createNote, getNote, listNotes } from '../lib/notes.js';

let db;

beforeEach(async () => {
  await new Promise((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME);
    req.onsuccess = resolve;
    req.onerror = () => reject(req.error);
    req.onblocked = resolve;
  });
  db = await openDb();
});

afterEach(() => db.close());

describe('createNote', () => {
  test('returns a note with generated id, timestamps, and empty fields', async () => {
    const before = Date.now();
    const note = await createNote(db);
    const after = Date.now();

    expect(note.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(note.title).toBe('');
    expect(note.body).toBe('');
    expect(note.attachmentIds).toEqual([]);
    expect(note.createdAt).toBeGreaterThanOrEqual(before);
    expect(note.createdAt).toBeLessThanOrEqual(after);
    expect(note.updatedAt).toBe(note.createdAt);
  });

  test('persists the note', async () => {
    const note = await createNote(db);
    const got = await getNote(db, note.id);
    expect(got).toEqual(note);
  });
});

describe('listNotes', () => {
  test('returns notes sorted by updatedAt DESC', async () => {
    const a = await createNote(db);
    await new Promise(r => setTimeout(r, 2));
    const b = await createNote(db);
    await new Promise(r => setTimeout(r, 2));
    const c = await createNote(db);

    const list = await listNotes(db);
    expect(list.map(n => n.id)).toEqual([c.id, b.id, a.id]);
  });

  test('returns empty array when there are no notes', async () => {
    const list = await listNotes(db);
    expect(list).toEqual([]);
  });
});
