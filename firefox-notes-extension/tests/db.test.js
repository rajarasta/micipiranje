import { openDb, DB_NAME, DB_VERSION, put, get, del, listByIndex, runTx } from '../lib/db.js';

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

describe('listByIndex', () => {
  test('returns records sorted by index DESC', async () => {
    const db = await openDb();
    await put(db, 'notes', { id: 'a', title: 'A', body: '', attachmentIds: [], createdAt: 1, updatedAt: 100 });
    await put(db, 'notes', { id: 'b', title: 'B', body: '', attachmentIds: [], createdAt: 1, updatedAt: 300 });
    await put(db, 'notes', { id: 'c', title: 'C', body: '', attachmentIds: [], createdAt: 1, updatedAt: 200 });

    const rows = await listByIndex(db, 'notes', 'updatedAt', 'prev');

    expect(rows.map(r => r.id)).toEqual(['b', 'c', 'a']);
    db.close();
  });
});

describe('runTx', () => {
  test('commits multi-store writes atomically', async () => {
    const db = await openDb();
    await runTx(db, ['notes', 'attachments'], 'readwrite', (tx) => {
      tx.objectStore('notes').put({ id: 'n1', title: 'x', body: '', attachmentIds: ['a1'], createdAt: 1, updatedAt: 1 });
      tx.objectStore('attachments').put({ id: 'a1', blob: new Blob(['x']), mimeType: 'image/png', filename: 'f.png', size: 1 });
    });

    expect(await get(db, 'notes', 'n1')).toBeDefined();
    expect(await get(db, 'attachments', 'a1')).toBeDefined();
    db.close();
  });

  test('rollback: throwing in callback aborts the transaction', async () => {
    const db = await openDb();
    await put(db, 'notes', { id: 'pre', title: 'pre', body: '', attachmentIds: [], createdAt: 1, updatedAt: 1 });

    await expect(runTx(db, ['notes'], 'readwrite', (tx) => {
      tx.objectStore('notes').put({ id: 'pre', title: 'changed', body: '', attachmentIds: [], createdAt: 1, updatedAt: 2 });
      throw new Error('abort me');
    })).rejects.toThrow('abort me');

    const got = await get(db, 'notes', 'pre');
    expect(got.title).toBe('pre');
    db.close();
  });
});
