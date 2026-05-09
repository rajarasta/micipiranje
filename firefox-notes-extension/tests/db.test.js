import { openDb, DB_NAME, DB_VERSION } from '../lib/db.js';

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
