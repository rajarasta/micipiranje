import { openDb, DB_NAME, DB_VERSION, put, get, del } from '../lib/db.js';

beforeEach(() => {
  return new Promise((resolve, reject) => {
    const req = indexedDB.deleteDatabase(DB_NAME);
    req.onsuccess = resolve;
    req.onerror = () => reject(req.error);
    req.onblocked = resolve;
  });
});

describe('openDb', () => {
  test('opens the database with both stores and the updatedAt index', async () => {
    const db = await openDb();
    expect(db.name).toBe(DB_NAME);
    expect(db.version).toBe(DB_VERSION);
    expect(Array.from(db.objectStoreNames).sort()).toEqual(['attachments', 'notes']);

    const tx = db.transaction('notes', 'readonly');
    const store = tx.objectStore('notes');
    expect(Array.from(store.indexNames)).toContain('updatedAt');

    db.close();
  });
});

describe('put / get / del', () => {
  test('put then get returns the same record', async () => {
    const db = await openDb();
    await put(db, 'notes', { id: 'n1', title: 'hi', body: '', attachmentIds: [], createdAt: 1, updatedAt: 1 });
    const got = await get(db, 'notes', 'n1');
    expect(got).toEqual({ id: 'n1', title: 'hi', body: '', attachmentIds: [], createdAt: 1, updatedAt: 1 });
    db.close();
  });

  test('get returns undefined for missing id', async () => {
    const db = await openDb();
    const got = await get(db, 'notes', 'missing');
    expect(got).toBeUndefined();
    db.close();
  });

  test('del removes the record', async () => {
    const db = await openDb();
    await put(db, 'notes', { id: 'n1', title: 'x', body: '', attachmentIds: [], createdAt: 1, updatedAt: 1 });
    await del(db, 'notes', 'n1');
    const got = await get(db, 'notes', 'n1');
    expect(got).toBeUndefined();
    db.close();
  });
});
