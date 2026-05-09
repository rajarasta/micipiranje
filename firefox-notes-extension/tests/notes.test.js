import { openDb, DB_NAME } from '../lib/db.js';
import { createNote, getNote, listNotes, updateNote, addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { deleteNote, searchNotes } from '../lib/notes.js';

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

describe('updateNote', () => {
  test('updates fields and bumps updatedAt', async () => {
    const note = await createNote(db);
    await new Promise(r => setTimeout(r, 2));

    const updated = await updateNote(db, note.id, { title: 'Hello', body: 'world' });

    expect(updated.title).toBe('Hello');
    expect(updated.body).toBe('world');
    expect(updated.updatedAt).toBeGreaterThan(note.updatedAt);
    expect(updated.createdAt).toBe(note.createdAt);
    expect(updated.attachmentIds).toEqual([]);
  });

  test('throws if note does not exist', async () => {
    await expect(updateNote(db, 'missing', { title: 'x' })).rejects.toThrow(/not found/i);
  });

  test('does not allow overwriting id, createdAt, or attachmentIds', async () => {
    const note = await createNote(db);
    const updated = await updateNote(db, note.id, {
      title: 'ok',
      id: 'evil',
      createdAt: 0,
      attachmentIds: ['injected']
    });
    expect(updated.id).toBe(note.id);
    expect(updated.createdAt).toBe(note.createdAt);
    expect(updated.attachmentIds).toEqual([]);
  });
});

describe('addAttachment', () => {
  test('stores blob and links attachment id to the note', async () => {
    const note = await createNote(db);
    const blob = new Blob(['fake-png-bytes'], { type: 'image/png' });

    const att = await addAttachment(db, note.id, blob, 'image/png', 'screenshot.png');

    expect(att.id).toMatch(/^[0-9a-f-]{36}$/);
    expect(att.mimeType).toBe('image/png');
    expect(att.filename).toBe('screenshot.png');
    expect(att.size).toBe(blob.size);

    const reloaded = await getNote(db, note.id);
    expect(reloaded.attachmentIds).toContain(att.id);
    expect(reloaded.updatedAt).toBeGreaterThanOrEqual(note.updatedAt);

    const stored = await getAttachment(db, att.id);
    expect(stored.blob).toBeInstanceOf(Blob);
    expect(stored.size).toBe(blob.size);
  });

  test('throws when note does not exist', async () => {
    const blob = new Blob(['x'], { type: 'image/png' });
    await expect(addAttachment(db, 'missing', blob, 'image/png', 'x.png'))
      .rejects.toThrow(/not found/i);
  });
});

describe('removeAttachment', () => {
  test('deletes the blob and removes the link from the note', async () => {
    const note = await createNote(db);
    const blob = new Blob(['x'], { type: 'image/png' });
    const att = await addAttachment(db, note.id, blob, 'image/png', 'x.png');

    await removeAttachment(db, note.id, att.id);

    const reloaded = await getNote(db, note.id);
    expect(reloaded.attachmentIds).not.toContain(att.id);
    expect(await getAttachment(db, att.id)).toBeUndefined();
  });

  test('is a no-op when attachment is not linked to that note', async () => {
    const note = await createNote(db);
    await expect(removeAttachment(db, note.id, 'never-existed')).resolves.toBeUndefined();
  });
});

describe('deleteNote', () => {
  test('cascades: deletes the note and all its attachments', async () => {
    const note = await createNote(db);
    const a1 = await addAttachment(db, note.id, new Blob(['1']), 'image/png', 'a.png');
    const a2 = await addAttachment(db, note.id, new Blob(['2']), 'image/png', 'b.png');

    await deleteNote(db, note.id);

    expect(await getNote(db, note.id)).toBeUndefined();
    expect(await getAttachment(db, a1.id)).toBeUndefined();
    expect(await getAttachment(db, a2.id)).toBeUndefined();
  });

  test('does not affect other notes attachments', async () => {
    const noteA = await createNote(db);
    const attA = await addAttachment(db, noteA.id, new Blob(['x']), 'image/png', 'a.png');
    const noteB = await createNote(db);
    const attB = await addAttachment(db, noteB.id, new Blob(['y']), 'image/png', 'b.png');

    await deleteNote(db, noteA.id);

    expect(await getAttachment(db, attA.id)).toBeUndefined();
    expect(await getAttachment(db, attB.id)).toBeDefined();
    expect(await getNote(db, noteB.id)).toBeDefined();
  });

  test('is a no-op for missing id', async () => {
    await expect(deleteNote(db, 'missing')).resolves.toBeUndefined();
  });
});

describe('searchNotes', () => {
  test('case-insensitive substring match on title and body', async () => {
    const a = await createNote(db);
    await updateNote(db, a.id, { title: 'Sastanak s timom', body: 'razgovarali smo o roadmapu' });
    const b = await createNote(db);
    await updateNote(db, b.id, { title: 'Ideja', body: 'možda dodati FEATURE x' });
    const c = await createNote(db);
    await updateNote(db, c.id, { title: 'Lista', body: 'kupiti kruh' });

    const all = await searchNotes(db, '');
    expect(all).toHaveLength(3);

    const byTitle = await searchNotes(db, 'sastanak');
    expect(byTitle.map(n => n.id)).toEqual([a.id]);

    const byBody = await searchNotes(db, 'feature');
    expect(byBody.map(n => n.id)).toEqual([b.id]);

    const none = await searchNotes(db, 'zzznomatch');
    expect(none).toEqual([]);
  });

  test('preserves DESC updatedAt ordering of results', async () => {
    const a = await createNote(db);
    await updateNote(db, a.id, { title: 'foo' });
    await new Promise(r => setTimeout(r, 2));
    const b = await createNote(db);
    await updateNote(db, b.id, { title: 'foo' });

    const results = await searchNotes(db, 'foo');
    expect(results.map(n => n.id)).toEqual([b.id, a.id]);
  });
});
