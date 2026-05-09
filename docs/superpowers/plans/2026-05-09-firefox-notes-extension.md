# Firefox Notes Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone Firefox MV3 extension that stores text notes plus clipboard-pasted image attachments, accessible via a toolbar popup, with all data in IndexedDB.

**Architecture:** Vanilla JS, no build step. Three-layer split: `lib/db.js` is a generic IndexedDB wrapper, `lib/notes.js` provides domain CRUD on top, `popup/popup.js` does UI. ES modules used both in extension and tests (Jest 29 with `--experimental-vm-modules`). Tests use `fake-indexeddb` for the DB layer and the domain layer.

**Tech Stack:** Firefox Manifest V3, ES modules, IndexedDB, Jest 29 + jest-environment-jsdom + fake-indexeddb. No frontend framework, no bundler.

**Spec:** [docs/superpowers/specs/2026-05-09-firefox-notes-extension-design.md](../specs/2026-05-09-firefox-notes-extension-design.md)

---

## File Structure

All paths relative to repo root. Extension lives in a new top-level directory `firefox-notes-extension/`.

```
firefox-notes-extension/
├── manifest.json                 # MV3 manifest (Firefox-specific gecko id)
├── icons/
│   ├── icon-48.png               # placeholder solid-color PNG
│   └── icon-96.png
├── popup/
│   ├── popup.html                # both list + editor views in one DOM, toggled
│   ├── popup.css                 # all styles
│   └── popup.js                  # entry, view switching, event handlers
├── lib/
│   ├── db.js                     # generic IndexedDB wrapper (open/get/put/del/list/tx)
│   ├── notes.js                  # domain CRUD: Note, Attachment, cascade delete, search
│   └── clipboard.js              # parsePaste(): image vs text, filename gen
├── tests/
│   ├── db.test.js
│   ├── notes.test.js
│   └── clipboard.test.js
├── package.json                  # dev deps: jest, jest-environment-jsdom, fake-indexeddb
└── jest.config.js                # ESM + jsdom + fake-indexeddb setup
```

Each module has one responsibility:

| File | Responsibility | Knows about |
|------|---------------|-------------|
| `lib/db.js` | Open the database, perform raw store operations, run multi-store transactions | IndexedDB only |
| `lib/notes.js` | Create / read / update / delete / search notes; cascade attachment delete; UUID generation; timestamps | The Note + Attachment shape, `db.js` |
| `lib/clipboard.js` | Pure parsing: given a `paste` event, return either an image Blob with metadata, or `null` (caller falls back to default behavior) | `ClipboardEvent` shape only |
| `popup/popup.js` | Render list/editor, wire up DOM events, debounce autosave, manage view state, toasts | DOM + `notes.js` + `clipboard.js` |

---

## Task 1: Scaffold project and verify temp install in Firefox

**Files:**
- Create: `firefox-notes-extension/manifest.json`
- Create: `firefox-notes-extension/popup/popup.html`
- Create: `firefox-notes-extension/popup/popup.js`
- Create: `firefox-notes-extension/popup/popup.css`
- Create: `firefox-notes-extension/icons/icon-48.png`
- Create: `firefox-notes-extension/icons/icon-96.png`
- Create: `firefox-notes-extension/package.json`
- Create: `firefox-notes-extension/jest.config.js`
- Create: `firefox-notes-extension/.gitignore`

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p firefox-notes-extension/{popup,lib,icons,tests}
```

- [ ] **Step 2: Generate placeholder icon PNGs**

Requires ImageMagick (`apt install imagemagick` if not present). If unavailable, any 48×48 and 96×96 PNG files work — the manifest just needs them to exist.

```bash
convert -size 48x48 xc:'#1f77b4' firefox-notes-extension/icons/icon-48.png
convert -size 96x96 xc:'#1f77b4' firefox-notes-extension/icons/icon-96.png
```

- [ ] **Step 3: Write `manifest.json`**

File: `firefox-notes-extension/manifest.json`

```json
{
  "manifest_version": 3,
  "name": "Bilješke",
  "version": "0.1.0",
  "description": "Lokalne bilješke s podrškom za paste slika.",
  "icons": {
    "48": "icons/icon-48.png",
    "96": "icons/icon-96.png"
  },
  "action": {
    "default_popup": "popup/popup.html",
    "default_title": "Bilješke",
    "default_icon": { "48": "icons/icon-48.png" }
  },
  "permissions": [],
  "browser_specific_settings": {
    "gecko": {
      "id": "biljeske@local",
      "strict_min_version": "115.0"
    }
  }
}
```

- [ ] **Step 4: Write a minimal `popup.html` so the popup loads**

File: `firefox-notes-extension/popup/popup.html`

```html
<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="UTF-8">
  <title>Bilješke</title>
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div id="app">Bilješke — učitavanje…</div>
  <script type="module" src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 5: Write a stub `popup.js` and `popup.css`**

File: `firefox-notes-extension/popup/popup.js`

```js
console.log('[notes] popup loaded');
```

File: `firefox-notes-extension/popup/popup.css`

```css
body {
  width: 400px;
  height: 600px;
  margin: 0;
  font-family: -moz-system-ui, system-ui, sans-serif;
  font-size: 14px;
}
#app {
  padding: 12px;
}
```

- [ ] **Step 6: Write `package.json` with dev tooling**

File: `firefox-notes-extension/package.json`

```json
{
  "name": "firefox-notes-extension",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --experimental-vm-modules node_modules/jest/bin/jest.js"
  },
  "devDependencies": {
    "jest": "^29.7.0",
    "jest-environment-jsdom": "^29.7.0",
    "fake-indexeddb": "^5.0.2"
  }
}
```

- [ ] **Step 7: Write `jest.config.js`**

File: `firefox-notes-extension/jest.config.js`

```js
export default {
  testEnvironment: 'jsdom',
  setupFiles: ['fake-indexeddb/auto'],
  testMatch: ['<rootDir>/tests/**/*.test.js'],
  transform: {}
};
```

- [ ] **Step 8: Write `.gitignore`**

File: `firefox-notes-extension/.gitignore`

```
node_modules/
*.log
.DS_Store
```

- [ ] **Step 9: Install dev dependencies**

Run from `firefox-notes-extension/`:

```bash
cd firefox-notes-extension && npm install
```

Expected: `node_modules/` populated, no errors. `package-lock.json` created.

- [ ] **Step 10: Manually verify the extension loads in Firefox**

1. Open Firefox.
2. Navigate to `about:debugging#/runtime/this-firefox`.
3. Click "Load Temporary Add-on…".
4. Select `firefox-notes-extension/manifest.json`.
5. Confirm "Bilješke" appears in the listing with no errors.
6. Click the extension icon in the toolbar — popup opens showing "Bilješke — učitavanje…".
7. Open the popup's DevTools (right-click the popup → Inspect) and confirm `[notes] popup loaded` appears in console.

- [ ] **Step 11: Commit**

```bash
git add firefox-notes-extension/
git commit -m "feat(notes-ext): scaffold MV3 extension with popup stub and jest setup"
```

---

## Task 2: `lib/db.js` — `openDb()` with schema

**Files:**
- Create: `firefox-notes-extension/lib/db.js`
- Create: `firefox-notes-extension/tests/db.test.js`

- [ ] **Step 1: Write the failing test**

File: `firefox-notes-extension/tests/db.test.js`

```js
import { openDb, DB_NAME, DB_VERSION } from '../lib/db.js';

beforeEach(() => {
  // reset fake-indexeddb between tests
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd firefox-notes-extension && npm test -- tests/db.test.js
```

Expected: FAIL with module not found (`../lib/db.js` does not exist yet).

- [ ] **Step 3: Implement `openDb()`**

File: `firefox-notes-extension/lib/db.js`

```js
export const DB_NAME = 'firefox-notes-db';
export const DB_VERSION = 1;

export function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error('DB open blocked by another connection'));
    req.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains('notes')) {
        const notes = db.createObjectStore('notes', { keyPath: 'id' });
        notes.createIndex('updatedAt', 'updatedAt', { unique: false });
      }
      if (!db.objectStoreNames.contains('attachments')) {
        db.createObjectStore('attachments', { keyPath: 'id' });
      }
    };
    req.onsuccess = () => resolve(req.result);
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
npm test -- tests/db.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/db.js firefox-notes-extension/tests/db.test.js
git commit -m "feat(notes-ext): add db.openDb with notes+attachments stores"
```

---

## Task 3: `lib/db.js` — generic `put`, `get`, `del`

**Files:**
- Modify: `firefox-notes-extension/lib/db.js`
- Modify: `firefox-notes-extension/tests/db.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/db.test.js`:

```js
import { put, get, del } from '../lib/db.js';

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/db.test.js
```

Expected: FAIL — `put`, `get`, `del` not exported.

- [ ] **Step 3: Implement `put`, `get`, `del`**

Append to `lib/db.js`:

```js
export function put(db, storeName, record) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).put(record);
    tx.oncomplete = () => resolve(record);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

export function get(db, storeName, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const req = tx.objectStore(storeName).get(id);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function del(db, storeName, id) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readwrite');
    tx.objectStore(storeName).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/db.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/db.js firefox-notes-extension/tests/db.test.js
git commit -m "feat(notes-ext): add db.put/get/del primitives"
```

---

## Task 4: `lib/db.js` — `listByIndex` and atomic `runTx`

**Files:**
- Modify: `firefox-notes-extension/lib/db.js`
- Modify: `firefox-notes-extension/tests/db.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/db.test.js`:

```js
import { listByIndex, runTx } from '../lib/db.js';

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/db.test.js
```

Expected: FAIL — `listByIndex`, `runTx` not exported.

- [ ] **Step 3: Implement `listByIndex` and `runTx`**

Append to `lib/db.js`:

```js
export function listByIndex(db, storeName, indexName, direction = 'prev') {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeName, 'readonly');
    const index = tx.objectStore(storeName).index(indexName);
    const req = index.openCursor(null, direction);
    const out = [];
    req.onsuccess = () => {
      const cursor = req.result;
      if (cursor) {
        out.push(cursor.value);
        cursor.continue();
      } else {
        resolve(out);
      }
    };
    req.onerror = () => reject(req.error);
  });
}

export function runTx(db, storeNames, mode, callback) {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(storeNames, mode);
    let userError = null;
    tx.oncomplete = () => (userError ? reject(userError) : resolve());
    tx.onerror = () => reject(userError || tx.error);
    tx.onabort = () => reject(userError || tx.error || new Error('Transaction aborted'));
    try {
      callback(tx);
    } catch (err) {
      userError = err;
      tx.abort();
    }
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/db.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/db.js firefox-notes-extension/tests/db.test.js
git commit -m "feat(notes-ext): add db.listByIndex and atomic runTx helper"
```

---

## Task 5: `lib/notes.js` — `createNote`, `getNote`, `listNotes`

**Files:**
- Create: `firefox-notes-extension/lib/notes.js`
- Create: `firefox-notes-extension/tests/notes.test.js`

- [ ] **Step 1: Write the failing tests**

File: `firefox-notes-extension/tests/notes.test.js`

```js
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/notes.test.js
```

Expected: FAIL — `../lib/notes.js` does not exist.

- [ ] **Step 3: Implement `createNote`, `getNote`, `listNotes`**

File: `firefox-notes-extension/lib/notes.js`

```js
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/notes.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): add notes.createNote/getNote/listNotes"
```

---

## Task 6: `lib/notes.js` — `updateNote`

**Files:**
- Modify: `firefox-notes-extension/lib/notes.js`
- Modify: `firefox-notes-extension/tests/notes.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/notes.test.js`:

```js
import { updateNote } from '../lib/notes.js';

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/notes.test.js
```

Expected: FAIL — `updateNote` not exported.

- [ ] **Step 3: Implement `updateNote`**

Append to `lib/notes.js`:

```js
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/notes.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): add notes.updateNote with field allowlist"
```

---

## Task 7: `lib/notes.js` — `addAttachment`, `removeAttachment`

**Files:**
- Modify: `firefox-notes-extension/lib/notes.js`
- Modify: `firefox-notes-extension/tests/notes.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/notes.test.js`:

```js
import { addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/notes.test.js
```

Expected: FAIL — symbols not exported.

- [ ] **Step 3: Implement attachment functions**

Append to `lib/notes.js`:

```js
import { runTx, del } from './db.js';

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
```

Note: `get` and `runTx` need to be re-imported into `notes.js`. Update the existing import at the top of `lib/notes.js` so it reads:

```js
import { put, get, listByIndex, runTx, del } from './db.js';
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/notes.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): add notes.addAttachment/removeAttachment with atomic tx"
```

---

## Task 8: `lib/notes.js` — `deleteNote` (cascade) and `searchNotes`

**Files:**
- Modify: `firefox-notes-extension/lib/notes.js`
- Modify: `firefox-notes-extension/tests/notes.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `tests/notes.test.js`:

```js
import { deleteNote, searchNotes } from '../lib/notes.js';

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/notes.test.js
```

Expected: FAIL — symbols not exported.

- [ ] **Step 3: Implement `deleteNote` and `searchNotes`**

Append to `lib/notes.js`:

```js
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/notes.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): add notes.deleteNote (cascade) and searchNotes"
```

---

## Task 9: `lib/clipboard.js` — `parsePaste` and `screenshotFilename`

**Files:**
- Create: `firefox-notes-extension/lib/clipboard.js`
- Create: `firefox-notes-extension/tests/clipboard.test.js`

- [ ] **Step 1: Write the failing tests**

File: `firefox-notes-extension/tests/clipboard.test.js`

```js
import { parsePaste, screenshotFilename, MAX_ATTACHMENT_BYTES } from '../lib/clipboard.js';

function makeEvent(items) {
  return {
    clipboardData: { items },
    preventDefault: jest.fn()
  };
}

function imageItem(blob) {
  return {
    type: blob.type,
    kind: 'file',
    getAsFile: () => blob
  };
}

function textItem(content) {
  return {
    type: 'text/plain',
    kind: 'string',
    getAsFile: () => null
  };
}

describe('parsePaste', () => {
  test('returns image payload and calls preventDefault when clipboard contains an image', () => {
    const blob = new Blob(['fake'], { type: 'image/png' });
    blob.size === undefined && Object.defineProperty(blob, 'size', { value: 4 });
    const ev = makeEvent([textItem(), imageItem(blob)]);

    const result = parsePaste(ev);

    expect(ev.preventDefault).toHaveBeenCalled();
    expect(result.kind).toBe('image');
    expect(result.blob).toBe(blob);
    expect(result.mimeType).toBe('image/png');
    expect(result.filename).toMatch(/^screenshot-\d{8}-\d{6}\.png$/);
  });

  test('returns null when clipboard has only text', () => {
    const ev = makeEvent([textItem()]);
    expect(parsePaste(ev)).toBeNull();
    expect(ev.preventDefault).not.toHaveBeenCalled();
  });

  test('returns rejected payload when image exceeds size limit', () => {
    const big = new Blob([new Uint8Array(10)], { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: MAX_ATTACHMENT_BYTES + 1 });
    const ev = makeEvent([imageItem(big)]);

    const result = parsePaste(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(result).toEqual({ kind: 'rejected', reason: 'too-large', size: MAX_ATTACHMENT_BYTES + 1 });
  });

  test('uses correct extension based on mimeType', () => {
    const jpg = new Blob(['x'], { type: 'image/jpeg' });
    Object.defineProperty(jpg, 'size', { value: 1 });
    const ev = makeEvent([imageItem(jpg)]);
    expect(parsePaste(ev).filename).toMatch(/\.jpe?g$/);
  });
});

describe('screenshotFilename', () => {
  test('formats timestamp as YYYYMMDD-HHmmss', () => {
    const fixed = new Date('2026-05-09T14:30:22.000Z');
    const name = screenshotFilename('image/png', fixed);
    expect(name).toMatch(/^screenshot-20260509-\d{6}\.png$/);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
npm test -- tests/clipboard.test.js
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement `clipboard.js`**

File: `firefox-notes-extension/lib/clipboard.js`

```js
export const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024;

const EXT_BY_MIME = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp',
  'image/bmp': 'bmp'
};

function pad(n, width = 2) {
  return String(n).padStart(width, '0');
}

export function screenshotFilename(mimeType, date = new Date()) {
  const ext = EXT_BY_MIME[mimeType] || 'bin';
  const ts = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `screenshot-${ts}.${ext}`;
}

export function parsePaste(event) {
  const items = event.clipboardData?.items ?? [];
  for (const item of items) {
    if (item.type && item.type.startsWith('image/')) {
      event.preventDefault();
      const blob = item.getAsFile();
      if (!blob) return null;
      if (blob.size > MAX_ATTACHMENT_BYTES) {
        return { kind: 'rejected', reason: 'too-large', size: blob.size };
      }
      return {
        kind: 'image',
        blob,
        mimeType: item.type,
        filename: screenshotFilename(item.type)
      };
    }
  }
  return null;
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
npm test -- tests/clipboard.test.js
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add firefox-notes-extension/lib/clipboard.js firefox-notes-extension/tests/clipboard.test.js
git commit -m "feat(notes-ext): add clipboard.parsePaste with size cap and filename"
```

---

## Task 10: Popup HTML + CSS — both views

**Files:**
- Modify: `firefox-notes-extension/popup/popup.html`
- Modify: `firefox-notes-extension/popup/popup.css`

- [ ] **Step 1: Replace `popup.html` with full markup**

File: `firefox-notes-extension/popup/popup.html`

```html
<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="UTF-8">
  <title>Bilješke</title>
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <main id="app">
    <!-- LIST VIEW -->
    <section id="view-list" class="view">
      <header class="bar">
        <h1>Bilješke</h1>
        <button id="btn-new" type="button">+ Nova</button>
      </header>
      <div class="search-row">
        <input id="search" type="search" placeholder="🔍 Pretraži bilješke…" autocomplete="off">
      </div>
      <ul id="note-list" class="note-list"></ul>
      <p id="empty-list" class="empty">Još nema bilješki.</p>
    </section>

    <!-- EDITOR VIEW -->
    <section id="view-editor" class="view hidden">
      <header class="bar">
        <button id="btn-back" type="button">← Natrag</button>
        <button id="btn-delete" type="button" class="danger">Obriši</button>
      </header>
      <input id="editor-title" type="text" placeholder="Naslov…" maxlength="200">
      <textarea id="editor-body" placeholder="Tekst bilješke…"></textarea>
      <section class="attachments">
        <h2>Privitci</h2>
        <ul id="attachment-list"></ul>
      </section>
    </section>

    <!-- TOAST -->
    <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>

    <!-- IMAGE PREVIEW MODAL -->
    <div id="modal" class="modal hidden">
      <img id="modal-img" alt="">
    </div>
  </main>
  <script type="module" src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Replace `popup.css` with full styles**

File: `firefox-notes-extension/popup/popup.css`

```css
* { box-sizing: border-box; }

body {
  width: 400px;
  height: 600px;
  margin: 0;
  font-family: -moz-system-ui, system-ui, sans-serif;
  font-size: 14px;
  background: #fafafa;
  color: #222;
}

#app, .view {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.hidden { display: none !important; }

.bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #e5e5e5;
  background: #fff;
}
.bar h1 { margin: 0; font-size: 15px; }

button {
  font: inherit;
  padding: 6px 10px;
  border: 1px solid #ccc;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
}
button:hover { background: #f0f0f0; }
button.danger { color: #b00; border-color: #f0c0c0; }

.search-row { padding: 8px 12px; border-bottom: 1px solid #eee; background: #fff; }
.search-row input {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font: inherit;
}

.note-list { list-style: none; margin: 0; padding: 0; overflow-y: auto; flex: 1; }
.note-card {
  padding: 10px 12px;
  border-bottom: 1px solid #eee;
  cursor: pointer;
}
.note-card:hover { background: #f4f8ff; }
.note-card .title { font-weight: 600; display: flex; justify-content: space-between; }
.note-card .preview { color: #666; font-size: 12px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.note-card .att-count { font-size: 12px; color: #888; }

.empty { text-align: center; color: #888; padding: 24px; }

#editor-title {
  font: inherit;
  font-size: 16px;
  font-weight: 600;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid #eee;
  outline: none;
}
#editor-body {
  flex: 1;
  font: inherit;
  padding: 10px 12px;
  border: 0;
  outline: none;
  resize: none;
  background: #fff;
}

.attachments {
  border-top: 1px solid #eee;
  background: #fff;
  max-height: 180px;
  overflow-y: auto;
}
.attachments h2 {
  font-size: 12px;
  text-transform: uppercase;
  color: #888;
  margin: 0;
  padding: 6px 12px;
  letter-spacing: 0.4px;
}
#attachment-list { list-style: none; margin: 0; padding: 0 6px 8px; }
.att-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 4px;
}
.att-item:hover { background: #f4f8ff; }
.att-item img.thumb {
  width: 36px;
  height: 36px;
  object-fit: cover;
  border-radius: 3px;
  cursor: pointer;
  background: #eee;
}
.att-item .name { flex: 1; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.att-item button { padding: 2px 8px; font-size: 12px; }

.toast {
  position: fixed;
  top: 12px;
  right: 12px;
  background: #222;
  color: #fff;
  padding: 8px 12px;
  border-radius: 4px;
  font-size: 12px;
  z-index: 100;
  max-width: 220px;
}
.toast.error { background: #b00; }

.modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.85);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  cursor: zoom-out;
}
.modal img { max-width: 92%; max-height: 92%; box-shadow: 0 4px 24px rgba(0,0,0,0.5); }
```

- [ ] **Step 3: Reload extension in Firefox and visually verify**

1. `about:debugging#/runtime/this-firefox` → click "Reload" on the Bilješke entry.
2. Click toolbar icon — popup opens.
3. List view visible, "+ Nova" button visible, search input visible, "Još nema bilješki." visible.
4. No console errors in popup DevTools.

- [ ] **Step 4: Commit**

```bash
git add firefox-notes-extension/popup/
git commit -m "feat(notes-ext): popup html and css for list+editor views"
```

---

## Task 11: `popup.js` — list view rendering and "Nova" navigation

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Replace `popup.js` with list rendering and view switching**

File: `firefox-notes-extension/popup/popup.js`

```js
import { openDb } from '../lib/db.js';
import { createNote, listNotes, getNote, searchNotes } from '../lib/notes.js';

const $ = (sel) => document.querySelector(sel);

const state = {
  db: null,
  currentNoteId: null,
  searchQuery: ''
};

async function init() {
  state.db = await openDb();
  bindStaticEvents();
  await renderList();
}

function bindStaticEvents() {
  $('#btn-new').addEventListener('click', onNewNoteClick);
  $('#search').addEventListener('input', onSearchInput);
  $('#btn-back').addEventListener('click', () => showList());
}

async function onNewNoteClick() {
  const note = await createNote(state.db);
  openEditor(note.id);
}

function onSearchInput(e) {
  state.searchQuery = e.target.value;
  renderList();
}

async function renderList() {
  const notes = state.searchQuery
    ? await searchNotes(state.db, state.searchQuery)
    : await listNotes(state.db);

  const ul = $('#note-list');
  ul.innerHTML = '';

  if (notes.length === 0) {
    $('#empty-list').classList.remove('hidden');
    return;
  }
  $('#empty-list').classList.add('hidden');

  for (const note of notes) {
    const li = document.createElement('li');
    li.className = 'note-card';
    li.dataset.id = note.id;
    li.innerHTML = `
      <div class="title">
        <span>${escapeHtml(note.title) || '<em>(bez naslova)</em>'}</span>
        ${note.attachmentIds.length ? `<span class="att-count">🖼 ${note.attachmentIds.length}</span>` : ''}
      </div>
      <div class="preview">${escapeHtml(note.body.slice(0, 120)) || '<em>—</em>'}</div>
    `;
    li.addEventListener('click', () => openEditor(note.id));
    ul.appendChild(li);
  }
}

function escapeHtml(str) {
  return String(str)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function openEditor(id) {
  state.currentNoteId = id;
  $('#view-list').classList.add('hidden');
  $('#view-editor').classList.remove('hidden');
  // Editor population happens in Task 12.
}

function showList() {
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  renderList();
}

init().catch(err => {
  console.error('[notes] init failed', err);
  // MV3 CSP forbids inline onclick — bind via addEventListener.
  $('#app').innerHTML = `<div class="empty">Ne mogu otvoriti pohranu. <button id="btn-retry" type="button">Pokušaj ponovno</button></div>`;
  $('#btn-retry').addEventListener('click', () => location.reload());
});
```

- [ ] **Step 2: Reload extension and verify**

1. Reload in `about:debugging`.
2. Click toolbar icon → empty state visible.
3. Click "+ Nova" → editor view appears (still empty inputs — population is Task 12), "← Natrag" returns to list.
4. After clicking Nova once, returning to list shows one card titled "(bez naslova)".
5. Type into the search box — list filters (visible only when notes exist; with one empty-titled note, search "x" returns nothing, search "" returns the empty-titled card).
6. No console errors.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/popup.js
git commit -m "feat(notes-ext): popup list view with new-note + search + navigation"
```

---

## Task 12: `popup.js` — editor view: load + autosave + flush + empty pruning

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Add editor lifecycle, autosave, and exit handling**

Add these helpers and modify `openEditor` / `showList` in `popup.js`. Replace the existing `openEditor` and `showList` and add the new functions:

```js
import { updateNote, deleteNote } from '../lib/notes.js';

let bodyDebounceTimer = null;
const BODY_DEBOUNCE_MS = 500;

async function openEditor(id) {
  state.currentNoteId = id;
  const note = await getNote(state.db, id);
  if (!note) {
    showList();
    return;
  }
  $('#editor-title').value = note.title;
  $('#editor-body').value = note.body;
  $('#view-list').classList.add('hidden');
  $('#view-editor').classList.remove('hidden');
  renderAttachments(note);  // implemented in Task 13

  // Bind editor-only events once per open (remove old listeners first)
  rebindEditorEvents();
  $('#editor-title').focus();
}

function rebindEditorEvents() {
  const title = $('#editor-title');
  const body = $('#editor-body');
  title.oninput = null;
  title.onblur = onTitleBlur;
  body.oninput = onBodyInput;
}

async function onTitleBlur() {
  if (!state.currentNoteId) return;
  await updateNote(state.db, state.currentNoteId, { title: $('#editor-title').value });
}

function onBodyInput() {
  if (bodyDebounceTimer) clearTimeout(bodyDebounceTimer);
  bodyDebounceTimer = setTimeout(flushBody, BODY_DEBOUNCE_MS);
}

async function flushBody() {
  if (bodyDebounceTimer) {
    clearTimeout(bodyDebounceTimer);
    bodyDebounceTimer = null;
  }
  if (!state.currentNoteId) return;
  await updateNote(state.db, state.currentNoteId, { body: $('#editor-body').value });
}

async function flushAndPrune() {
  if (!state.currentNoteId) return;
  await flushBody();
  // Title save on blur is synchronous from user perspective;
  // ensure latest value persisted explicitly:
  await updateNote(state.db, state.currentNoteId, { title: $('#editor-title').value });

  const note = await getNote(state.db, state.currentNoteId);
  if (note && !note.title.trim() && !note.body.trim() && note.attachmentIds.length === 0) {
    await deleteNote(state.db, state.currentNoteId);
  }
}

async function showList() {
  await flushAndPrune();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  await renderList();
}

// Handle popup close — pagehide fires when the popup is dismissed.
window.addEventListener('pagehide', () => {
  // Best-effort sync flush. updateNote is async; we kick it off and IndexedDB
  // tx will continue in the background even after pagehide returns.
  flushAndPrune().catch(err => console.error('[notes] flush on hide failed', err));
});
```

Also: add `renderAttachments(note)` as a placeholder (real implementation lands in Task 13):

```js
function renderAttachments(note) {
  $('#attachment-list').innerHTML = '';
}
```

And update the `bindStaticEvents` function to no longer override `btn-back`:

Replace:

```js
$('#btn-back').addEventListener('click', () => showList());
```

with:

```js
$('#btn-back').addEventListener('click', () => { showList().catch(err => console.error('[notes]', err)); });
```

- [ ] **Step 2: Reload extension and verify**

1. Reload extension. Click "+ Nova".
2. Type a title → click "← Natrag" → list shows the note with that title.
3. Open it again → type body → wait 1s → close popup by clicking outside → reopen → body persisted.
4. Click "+ Nova" → leave fields empty → "← Natrag" → list does NOT contain a "(bez naslova)" entry (was pruned).
5. No console errors.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/popup.js
git commit -m "feat(notes-ext): editor autosave with flush-on-exit and empty-note pruning"
```

---

## Task 13: `popup.js` — paste handler + attachment rendering + thumbnail modal + remove

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Add paste handling, attachment rendering, and modal preview**

Add to `popup.js`:

```js
import { addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { parsePaste } from '../lib/clipboard.js';

const objectUrls = new Map();  // attachmentId → objectUrl, for cleanup

function renderAttachments(note) {
  const ul = $('#attachment-list');
  ul.innerHTML = '';
  for (const attId of note.attachmentIds) {
    renderAttachmentRow(attId).catch(err => console.error('[notes] att render', err));
  }
}

async function renderAttachmentRow(attId) {
  const att = await getAttachment(state.db, attId);
  const li = document.createElement('li');
  li.className = 'att-item';
  li.dataset.id = attId;

  if (!att) {
    li.innerHTML = `<span class="thumb">⚠</span><span class="name">privitak nedostaje</span><button type="button">✕</button>`;
  } else {
    const url = URL.createObjectURL(att.blob);
    objectUrls.set(attId, url);
    const img = document.createElement('img');
    img.className = 'thumb';
    img.alt = '';
    img.src = url;
    img.onerror = () => { img.replaceWith(document.createTextNode('⚠')); };
    img.addEventListener('click', () => openModal(url));

    const name = document.createElement('span');
    name.className = 'name';
    name.textContent = `${att.filename} (${formatSize(att.size)})`;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = '✕';
    btn.addEventListener('click', () => removeAttachmentClick(attId));

    li.append(img, name, btn);
  }
  $('#attachment-list').appendChild(li);
}

async function removeAttachmentClick(attId) {
  if (!confirm('Obrisati ovaj privitak?')) return;
  await removeAttachment(state.db, state.currentNoteId, attId);
  releaseObjectUrl(attId);
  const note = await getNote(state.db, state.currentNoteId);
  if (note) renderAttachments(note);
}

function releaseObjectUrl(attId) {
  const url = objectUrls.get(attId);
  if (url) {
    URL.revokeObjectURL(url);
    objectUrls.delete(attId);
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function openModal(src) {
  $('#modal-img').src = src;
  $('#modal').classList.remove('hidden');
}

$('#modal').addEventListener('click', () => {
  $('#modal').classList.add('hidden');
  $('#modal-img').src = '';
});

// Wire up paste: capture Ctrl+V on the textarea
function bindPasteHandler() {
  $('#editor-body').addEventListener('paste', onPaste);
}

async function onPaste(e) {
  if (!state.currentNoteId) return;
  const result = parsePaste(e);
  if (!result) return;

  if (result.kind === 'rejected') {
    showToast(`Slika je prevelika (${formatSize(result.size)}, max 50 MB)`, 'error');
    return;
  }

  try {
    const att = await addAttachment(state.db, state.currentNoteId, result.blob, result.mimeType, result.filename);
    showToast(`Slika dodana (${formatSize(att.size)})`);
    const note = await getNote(state.db, state.currentNoteId);
    if (note) renderAttachments(note);
  } catch (err) {
    console.error('[notes] addAttachment failed', err);
    if (err.name === 'QuotaExceededError') {
      showToast('Nema dovoljno prostora. Obriši stare bilješke ili privitke.', 'error');
    } else {
      showToast('Greška pri spremanju slike.', 'error');
    }
  }
}

let toastTimer = null;
function showToast(message, kind = 'info') {
  const el = $('#toast');
  el.textContent = message;
  el.classList.remove('hidden', 'error');
  if (kind === 'error') el.classList.add('error');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2000);
}
```

Modify `init` to also call `bindPasteHandler()`:

Replace:

```js
async function init() {
  state.db = await openDb();
  bindStaticEvents();
  await renderList();
}
```

with:

```js
async function init() {
  state.db = await openDb();
  bindStaticEvents();
  bindPasteHandler();
  await renderList();
}
```

Also: in `showList()`, before clearing `currentNoteId`, release object URLs to avoid leaks:

Replace:

```js
async function showList() {
  await flushAndPrune();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  await renderList();
}
```

with:

```js
async function showList() {
  await flushAndPrune();
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  await renderList();
}
```

- [ ] **Step 2: Reload extension and run paste smoke test**

1. Reload extension. Open a note in editor.
2. Take an OS screenshot that copies to clipboard:
   - GNOME: `gnome-screenshot -ac` (or PrintScreen + select-area-and-copy in modern GNOME)
   - Flameshot: `flameshot gui` then "Copy to clipboard" button
   - KDE: Spectacle → "Copy to clipboard"
   - Or take any image, right-click → Copy in another browser tab.
3. Click into the body textarea, press Ctrl+V.
4. Verify: a row with the thumbnail appears in "Privitci". Toast "Slika dodana (… KB)" appears top-right and fades.
5. Click the thumbnail → image opens in modal at full size; click anywhere → modal closes.
6. Click ✕ next to the attachment → confirm → row disappears.
7. Re-paste, then click "← Natrag", reopen the note → attachment still there.
8. No console errors.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/popup.js
git commit -m "feat(notes-ext): paste-image attachment with thumb, modal, and toast"
```

---

## Task 14: `popup.js` — delete-note button

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Wire up the delete button**

Add to `bindStaticEvents()`:

```js
  $('#btn-delete').addEventListener('click', onDeleteNoteClick);
```

Add the handler:

```js
async function onDeleteNoteClick() {
  if (!state.currentNoteId) return;
  if (!confirm('Obrisati ovu bilješku i sve privitke?')) return;
  await deleteNote(state.db, state.currentNoteId);
  // Skip flushAndPrune: note is already gone
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  await renderList();
}
```

- [ ] **Step 2: Reload and verify**

1. Reload extension. Create a note, paste a screenshot, click "← Natrag".
2. Reopen the note. Click "Obriši" → confirm dialog → confirm.
3. List view shows: note gone.
4. DevTools → Storage → IndexedDB → `firefox-notes-db` → `attachments` store: empty (orphan check).
5. No console errors.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/popup.js
git commit -m "feat(notes-ext): delete-note button with cascade and confirmation"
```

---

## Task 15: Manual smoke test pass

**Files:** none — verification only.

- [ ] **Step 1: Run all unit tests**

```bash
cd firefox-notes-extension && npm test
```

Expected: all tests in `db.test.js`, `notes.test.js`, `clipboard.test.js` pass. No skipped tests.

- [ ] **Step 2: Reload the extension fresh in Firefox**

1. Open `about:debugging#/runtime/this-firefox`.
2. Remove any old "Bilješke" temp add-on (Remove button).
3. Load Temporary Add-on → select `firefox-notes-extension/manifest.json`.
4. Open extension popup → DevTools console open → no errors.

- [ ] **Step 3: Run the spec smoke checklist**

Walk through every step from the design spec. All must pass:

1. Open popup → empty state visible ("Još nema bilješki.").
2. Click "+ Nova" → enter title "Test 1" → enter body "Hello world" → close popup by clicking outside.
3. Reopen popup → "Test 1" card visible at top.
4. Open the note, take an OS screenshot, paste with Ctrl+V → toast appears, attachment row appears.
5. Reload the entire Firefox profile (close Firefox, reopen). Reload the temp add-on. Open popup → note "Test 1" with attachment intact and thumbnail renders.
6. Delete the note via "Obriši" button. DevTools → Storage → IndexedDB → `firefox-notes-db` → `notes` and `attachments` stores both empty.
7. Create > 100 notes by running this in the popup DevTools console:

   ```js
   const { openDb } = await import(browser.runtime.getURL('lib/db.js'));
   const { createNote, updateNote } = await import(browser.runtime.getURL('lib/notes.js'));
   const db = await openDb();
   for (let i = 0; i < 120; i++) {
     const n = await createNote(db);
     await updateNote(db, n.id, { title: `Note ${i}`, body: `body ${i}` });
   }
   db.close();
   ```

   Reload popup → time from click-to-render < 500 ms (use Performance tab if uncertain).
8. Type "note 50" in search → only that card appears.

- [ ] **Step 4: Commit if any final fixes were needed**

If steps 1–8 all pass without any code changes, no commit needed; mark task complete. If a fix was required, commit it with a descriptive message.

- [ ] **Step 5: Tag the MVP release**

```bash
git tag -a notes-ext-v0.1.0 -m "Firefox notes extension MVP"
```
