# Bilješke Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) for tracking.

**Goal:** Expand the existing `firefox-notes-extension` with the Bilješke redesign — toolbar bracket icon, tray launcher, redesigned popup list+editor, new full-tab rich mode, shortcuts modal, export modal, and supporting data-model fields (`pinned`, `tags`, `thumbnailBlob`).

**Architecture:** Vanilla JS + IndexedDB, MV3, no build step. Tokens & icons in `popup/tokens.css` and `popup/icons.js` (shared by popup and tab). `popup/popup.js` gains a view state machine (launcher | list | editor). New `tab/` directory hosts `tab.html`, `tab.css`, `tab.js` reusing the same `lib/` modules.

**Tech Stack:** ES modules, Jest 29 + jsdom + fake-indexeddb (existing). Geist + Geist Mono via Google Fonts CSS link.

**Reference:** [krmahilson/Note taking app/design_handoff_biljeske_redesign/README.md](../../krmahilson/Note%20taking%20app/design_handoff_biljeske_redesign/README.md) is the canonical spec — preserve copy, tokens, layouts. Design files at [krmahilson/Note taking app/design_handoff_biljeske_redesign/design_files/](../../krmahilson/Note%20taking%20app/design_handoff_biljeske_redesign/design_files/) include `styles.css` (994 lines; class names match implementation targets), `icons.jsx`, and `comp/{popup,launcher,fulltab,icons-set}.jsx`. The handoff docs are read-only — never modify them.

**Decisions taken (confirmed with user):**
1. Tag chip strip: derived from history (top-4 most-used + "Sve").
2. Thumbnails: persisted 72×72 PNG generated at attachment-save time, stored in IndexedDB.
3. Pin sort: pinned notes float into a separate "Pribadane" group above "Danas".
4. ⌘N hotkey: popup/tab scope only (no global Firefox hotkey, no `commands` permission).

---

## File Structure (additions and modifications)

```
firefox-notes-extension/
├── manifest.json               # MODIFY — bracket icons in default_icon, default_title
├── icons/
│   ├── bracket-16.png          # NEW
│   ├── bracket-32.png          # NEW
│   ├── bracket-48.png          # NEW
│   ├── icon-48.png             # KEEP for now (legacy fallback)
│   └── icon-96.png             # KEEP
├── popup/
│   ├── popup.html              # MODIFY — add launcher section, redesigned list & editor markup
│   ├── popup.css               # REPLACE — switch to redesign CSS that uses tokens
│   ├── tokens.css              # NEW — design tokens (colors, fonts, radii, shadows)
│   ├── icons.js                # NEW — SVG icon strings
│   └── popup.js                # MODIFY — view state machine, launcher logic, new render
├── tab/
│   ├── tab.html                # NEW
│   ├── tab.css                 # NEW
│   └── tab.js                  # NEW
├── lib/
│   ├── notes.js                # MODIFY — add togglePin, setTags; thumbnail generation in addAttachment
│   ├── thumbnail.js            # NEW — 72×72 downscaler using OffscreenCanvas (test fallback to mock)
│   ├── grouping.js             # NEW — pure date-grouping helper (Pribadane/Danas/Jučer/Ovaj tjedan)
│   ├── tags.js                 # NEW — pure helper: top-4 tags from notes + "Sve"
│   ├── search.js               # NEW — match-highlighting helper (segment text into runs)
│   └── export.js               # NEW — md/json/zip serialisers
├── lib/vendor/
│   └── jszip.min.js            # NEW (vendored) — for .zip export
└── tests/
    ├── thumbnail.test.js       # NEW
    ├── grouping.test.js        # NEW
    ├── tags.test.js            # NEW
    ├── search.test.js          # NEW
    ├── export.test.js          # NEW
    └── notes.test.js           # MODIFY — add tests for togglePin, setTags, thumbnail generation
```

Each module has one job:
- `tokens.css` — design vars only.
- `icons.js` — pure SVG strings keyed by name.
- `thumbnail.js` — Blob → Blob (72×72 PNG).
- `grouping.js` — array of notes → ordered groups.
- `tags.js` — array of notes → top-4 tag list.
- `search.js` — text + query → array of `{text, hi}` runs.
- `export.js` — array of notes → Blob (md/json/zip).
- `popup.js` / `tab.js` — UI rendering + state machine; both consume `lib/`.

---

## Phase A — Foundations (tokens, icons, fonts)

### Task A1: Add `popup/tokens.css`

**Files:**
- Create: `firefox-notes-extension/popup/tokens.css`

- [ ] **Step 1: Copy the `:root` block from the handoff README** (section "Design tokens"). Paste verbatim into the new file. Do not add extra rules; tokens only.

- [ ] **Step 2: Add Google Fonts import at top of file**

```css
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500&display=swap');

:root {
  /* ... full token block from README ... */
}
```

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/tokens.css
git commit -m "feat(notes-ext): add design tokens (Geist fonts + warm-paper palette)"
```

---

### Task A2: Generate bracket toolbar icons

**Files:**
- Create: `firefox-notes-extension/icons/bracket-16.png`, `bracket-32.png`, `bracket-48.png`

- [ ] **Step 1: Find a PNG generator path**. Try in order:
  1. `convert` / `magick` (ImageMagick)
  2. Python PIL (`from PIL import Image, ImageDraw`)
  3. Node + `sharp` (`npm i -g sharp-cli` or `npx sharp-cli`)

  If only PIL is present, draw the bracket SVG manually. Reference SVG (from README):

  ```svg
  <svg viewBox="0 0 32 32" fill="none" width="32" height="32">
    <rect x="3" y="3" width="26" height="26" rx="6" fill="#fbfaf6" stroke="#1c1a17" stroke-width="2"/>
    <path d="M11 10v12M11 10h3M11 22h3" stroke="#1c1a17" stroke-width="2" stroke-linecap="round"/>
    <path d="M21 10v12M21 10h-3M21 22h-3" stroke="#1c1a17" stroke-width="2" stroke-linecap="round"/>
  </svg>
  ```

  Easiest path: write the SVG to a temp file, then `rsvg-convert` (apt: `librsvg2-bin`) or fallback to a Python script using PIL drawing primitives (rounded rect + lines).

- [ ] **Step 2: Verify the three PNGs**: each is the right pixel size and looks like a bracket icon. Open one with `xdg-open` or `file <path>` to confirm dimensions.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/icons/bracket-16.png firefox-notes-extension/icons/bracket-32.png firefox-notes-extension/icons/bracket-48.png
git commit -m "feat(notes-ext): add bracket toolbar icon at 16/32/48"
```

---

### Task A3: Wire icons in `manifest.json`

**Files:**
- Modify: `firefox-notes-extension/manifest.json`

- [ ] **Step 1: Update manifest.json `action` block** to use the new bracket icons:

```json
"action": {
  "default_popup": "popup/popup.html",
  "default_title": "Bilješke",
  "default_icon": {
    "16": "icons/bracket-16.png",
    "32": "icons/bracket-32.png",
    "48": "icons/bracket-48.png"
  }
}
```

Also update the top-level `"icons"` block:

```json
"icons": {
  "16": "icons/bracket-16.png",
  "32": "icons/bracket-32.png",
  "48": "icons/bracket-48.png"
}
```

- [ ] **Step 2: Commit**

```bash
git add firefox-notes-extension/manifest.json
git commit -m "feat(notes-ext): wire bracket icons in manifest"
```

---

### Task A4: Add `popup/icons.js` SVG module

**Files:**
- Create: `firefox-notes-extension/popup/icons.js`

- [ ] **Step 1: Read the handoff `design_files/icons.jsx`** to see the icon set: `Plus, Search, Trash, X, Image, ExternalLink, List, Pencil, Download, Keyboard, Tag, Pin, Lock, Filter, More, Paperclip`. Each is an inline SVG.

- [ ] **Step 2: Create `popup/icons.js` exporting an `icons` map** of SVG strings:

```js
export const icons = {
  plus: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M8 3v10M3 8h10"/></svg>`,
  search: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><circle cx="7" cy="7" r="4.5"/><path d="m13 13-2.5-2.5"/></svg>`,
  trash: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11M6 4V2.5h4V4M4 4v9.5a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V4"/></svg>`,
  x: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/></svg>`,
  image: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><circle cx="6" cy="6.5" r="1"/><path d="m2 11 3.5-3 4 3.5L12 9l2 1.5"/></svg>`,
  externalLink: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3h4v4M13 3 8 8M11 9v3.5a1 1 0 0 1-1 1H3.5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1H7"/></svg>`,
  list: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M3 4.5h10M3 8h10M3 11.5h10"/></svg>`,
  pencil: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="m3 13 2.5-.5L13 5l-2-2-7.5 7.5L3 13z"/></svg>`,
  download: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v8M5 7l3 3 3-3M3 13h10"/></svg>`,
  keyboard: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="1.5" y="4" width="13" height="8" rx="1.5"/><path d="M4 7h.01M7 7h.01M10 7h.01M13 7h.01M5 9.5h6" stroke-linecap="round"/></svg>`,
  tag: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M2.5 7.5V3a.5.5 0 0 1 .5-.5h4.5l6 6-5 5-6-6Z"/><circle cx="5.5" cy="5.5" r="0.6" fill="currentColor"/></svg>`,
  pin: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2.5l4 4-2 1L8 10l-2-2 2.5-3.5 1-2zM5.5 10.5 2 14M9 8l-3-3"/></svg>`,
  lock: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5 7V5a3 3 0 0 1 6 0v2" stroke-linecap="round"/></svg>`,
  filter: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h12l-4.5 6V13l-3 1V9L2 3z"/></svg>`,
  more: `<svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor"><circle cx="3.5" cy="8" r="1.2"/><circle cx="8" cy="8" r="1.2"/><circle cx="12.5" cy="8" r="1.2"/></svg>`,
  paperclip: `<svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11.5 7 7 11.5a2.5 2.5 0 0 1-3.5-3.5l5.5-5.5a3 3 0 1 1 4.2 4.2L7 12.5"/></svg>`,
  bracket: `<svg viewBox="0 0 32 32" fill="none" width="22" height="22"><path d="M11 10v12M11 10h3M11 22h3M21 10v12M21 10h-3M21 22h-3" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`
};

export function iconHtml(name) {
  return icons[name] || '';
}
```

Tweak any glyph that doesn't render cleanly at 14×14.

- [ ] **Step 2: No tests for this file** — pure data. UI smoke verifies render later.

- [ ] **Step 3: Commit**

```bash
git add firefox-notes-extension/popup/icons.js
git commit -m "feat(notes-ext): add icons.js SVG module"
```

---

## Phase B — Data model additions

### Task B1: Extend `Note` shape and add `togglePin` + `setTags` (TDD)

**Files:**
- Modify: `firefox-notes-extension/lib/notes.js`
- Modify: `firefox-notes-extension/tests/notes.test.js`

The `Note` shape gains optional fields `pinned: boolean`, `tags: string[]`. New notes get default `pinned: false, tags: []`. Existing notes lacking these fields are read as if they had defaults — no migration required.

- [ ] **Step 1: Add failing tests** for:
  - `createNote` returns a note with `pinned === false` and `tags === []`.
  - `togglePin(db, id)` flips `pinned` and bumps `updatedAt`. Throws on missing id.
  - `setTags(db, id, tags)` lowercases each entry, dedupes, and stores. Throws on missing id. Empty array clears tags.
  - `getNote` returns `pinned: false, tags: []` defaults for legacy records that omit these fields.

```js
describe('togglePin', () => {
  test('flips pinned and bumps updatedAt', async () => {
    const note = await createNote(db);
    expect(note.pinned).toBe(false);
    await new Promise(r => setTimeout(r, 2));
    const after = await togglePin(db, note.id);
    expect(after.pinned).toBe(true);
    expect(after.updatedAt).toBeGreaterThan(note.updatedAt);
    const after2 = await togglePin(db, note.id);
    expect(after2.pinned).toBe(false);
  });
  test('throws on missing id', async () => {
    await expect(togglePin(db, 'missing')).rejects.toThrow(/not found/i);
  });
});

describe('setTags', () => {
  test('lowercases and dedupes tags', async () => {
    const note = await createNote(db);
    const after = await setTags(db, note.id, ['Posao', 'POSAO', 'Dizajn']);
    expect(after.tags).toEqual(['posao', 'dizajn']);
  });
  test('empty array clears tags', async () => {
    const note = await createNote(db);
    await setTags(db, note.id, ['x']);
    const cleared = await setTags(db, note.id, []);
    expect(cleared.tags).toEqual([]);
  });
});

describe('legacy record defaults', () => {
  test('getNote returns pinned: false and tags: [] when absent', async () => {
    // Use raw db.put to write a note without the new fields.
    const legacy = { id: crypto.randomUUID(), title: '', body: 'old', attachmentIds: [], createdAt: 1, updatedAt: 1 };
    await put(db, 'notes', legacy);
    const got = await getNote(db, legacy.id);
    expect(got.pinned).toBe(false);
    expect(got.tags).toEqual([]);
  });
});
```

(Adapt imports — `setTags`, `togglePin`, `put` need to be in scope.)

- [ ] **Step 2: Verify tests fail.**

- [ ] **Step 3: Implement** in `lib/notes.js`:

```js
export async function togglePin(db, id) {
  const existing = await getNote(db, id);
  if (!existing) throw new Error(`Note not found: ${id}`);
  const updated = { ...existing, pinned: !existing.pinned, updatedAt: Date.now() };
  await put(db, 'notes', updated);
  return updated;
}

export async function setTags(db, id, tags) {
  const existing = await getNote(db, id);
  if (!existing) throw new Error(`Note not found: ${id}`);
  const normalized = Array.from(new Set(tags.map(t => String(t).toLowerCase().trim()).filter(Boolean)));
  const updated = { ...existing, tags: normalized, updatedAt: Date.now() };
  await put(db, 'notes', updated);
  return updated;
}
```

Modify `createNote` to seed `pinned: false, tags: []`:

```js
const note = {
  id: crypto.randomUUID(),
  title: '',
  body: '',
  attachmentIds: [],
  pinned: false,
  tags: [],
  createdAt: now,
  updatedAt: now
};
```

Modify `getNote` (and through it `listNotes`) to return defaults for legacy records. Wrap the existing `get` call:

```js
export async function getNote(db, id) {
  const raw = await get(db, 'notes', id);
  if (!raw) return raw;
  return { pinned: false, tags: [], ...raw };
}

export async function listNotes(db) {
  const rows = await listByIndex(db, 'notes', 'updatedAt', 'prev');
  return rows.map(r => ({ pinned: false, tags: [], ...r }));
}
```

- [ ] **Step 4: Tests pass.** Full suite runs.

- [ ] **Step 5: Commit.**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): add pinned + tags fields with togglePin/setTags"
```

---

### Task B2: Thumbnail generation (TDD)

**Files:**
- Create: `firefox-notes-extension/lib/thumbnail.js`
- Create: `firefox-notes-extension/tests/thumbnail.test.js`

The thumbnail module accepts a Blob (image) and returns a 72×72 PNG Blob. In the browser it uses `OffscreenCanvas` + `createImageBitmap`. In jsdom there's no canvas — the test environment must mock these. Strategy:

- Module API: `generateThumbnail(blob, size = 72): Promise<Blob>`.
- In the browser, call `createImageBitmap(blob)` then draw to an `OffscreenCanvas(size, size)` with object-fit-cover math, then `canvas.convertToBlob({ type: 'image/png' })`.
- In tests, mock `globalThis.createImageBitmap` and `globalThis.OffscreenCanvas` in the test setup file. The mock `OffscreenCanvas` returns a fake `getContext('2d')` that no-ops draws and a `convertToBlob` that returns a tiny PNG-shaped Blob.

- [ ] **Step 1: Write failing tests** in `tests/thumbnail.test.js`:

```js
import { generateThumbnail } from '../lib/thumbnail.js';

beforeEach(() => {
  globalThis.createImageBitmap = jest.fn(async (blob) => ({
    width: 200,
    height: 100,
    close() {}
  }));
  class FakeCtx {
    drawImage() {}
    fillStyle = '';
    fillRect() {}
  }
  globalThis.OffscreenCanvas = class {
    constructor(w, h) { this.width = w; this.height = h; }
    getContext() { return new FakeCtx(); }
    async convertToBlob({ type } = {}) {
      return new Blob([new Uint8Array([0x89, 0x50, 0x4E, 0x47])], { type: type || 'image/png' });
    }
  };
});

describe('generateThumbnail', () => {
  test('returns a 72x72 PNG Blob by default', async () => {
    const input = new Blob([new Uint8Array([1,2,3])], { type: 'image/png' });
    const out = await generateThumbnail(input);
    expect(out).toBeInstanceOf(Blob);
    expect(out.type).toBe('image/png');
    expect(out.size).toBeGreaterThan(0);
  });

  test('respects custom size', async () => {
    const input = new Blob([new Uint8Array([1])], { type: 'image/png' });
    const out = await generateThumbnail(input, 32);
    expect(out).toBeInstanceOf(Blob);
  });

  test('rejects non-image blobs', async () => {
    const input = new Blob(['hello'], { type: 'text/plain' });
    await expect(generateThumbnail(input)).rejects.toThrow(/image/i);
  });
});
```

- [ ] **Step 2: Implement** `lib/thumbnail.js`:

```js
export async function generateThumbnail(blob, size = 72) {
  if (!blob || !blob.type || !blob.type.startsWith('image/')) {
    throw new Error('Cannot thumbnail non-image blob');
  }
  const bitmap = await createImageBitmap(blob);
  const { width: w, height: h } = bitmap;
  // object-fit: cover
  const scale = Math.max(size / w, size / h);
  const dw = w * scale;
  const dh = h * scale;
  const dx = (size - dw) / 2;
  const dy = (size - dh) / 2;

  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ece7db';
  ctx.fillRect(0, 0, size, size);
  ctx.drawImage(bitmap, dx, dy, dw, dh);
  if (bitmap.close) bitmap.close();
  return await canvas.convertToBlob({ type: 'image/png' });
}
```

- [ ] **Step 3: Tests pass. Commit.**

```bash
git add firefox-notes-extension/lib/thumbnail.js firefox-notes-extension/tests/thumbnail.test.js
git commit -m "feat(notes-ext): add generateThumbnail (72x72 PNG)"
```

---

### Task B3: Wire thumbnails into `addAttachment` (TDD)

**Files:**
- Modify: `firefox-notes-extension/lib/notes.js`
- Modify: `firefox-notes-extension/tests/notes.test.js`

When an image is added, generate a 72×72 thumbnail and store it on the attachment. Schema additions on the attachment record: `thumbBlob: Blob | null` (null for non-image attachments).

- [ ] **Step 1: Failing test** in `notes.test.js` — verifies `addAttachment` for an image returns/stores a `thumbBlob` field that is a Blob, and for a non-image attachment `thumbBlob === null`. Also verify that thumbnail generation failures don't fail the whole `addAttachment` (fall back to null + console.warn).

- [ ] **Step 2: Implement** — at top of `notes.js`:

```js
import { generateThumbnail } from './thumbnail.js';
```

Modify `addAttachment` so the attachment record has an extra `thumbBlob` slot:

```js
const att = {
  id: crypto.randomUUID(),
  blob,
  mimeType,
  filename,
  size: blob.size,
  thumbBlob: null
};
if (mimeType.startsWith('image/')) {
  try {
    att.thumbBlob = await generateThumbnail(blob, 72);
  } catch (err) {
    console.warn('[notes] thumbnail failed', err);
  }
}
// ... unchanged tx wrapper ...
```

- [ ] **Step 3: Tests pass. Commit.**

```bash
git add firefox-notes-extension/lib/notes.js firefox-notes-extension/tests/notes.test.js
git commit -m "feat(notes-ext): persist 72x72 thumbnails on image attachments"
```

---

### Task B4: `lib/grouping.js` — date-grouped notes (TDD)

**Files:**
- Create: `firefox-notes-extension/lib/grouping.js`
- Create: `firefox-notes-extension/tests/grouping.test.js`

The function returns ordered groups: `Pribadane`, `Danas`, `Jučer`, `Ovaj tjedan`, `Stariji`. Uses `now` so tests can pin time.

- [ ] **Step 1: Failing tests** verifying:
  - Pinned notes go to `Pribadane` regardless of date.
  - Non-pinned notes from today go to `Danas`.
  - Non-pinned from yesterday → `Jučer`.
  - Non-pinned from 3-7 days ago → `Ovaj tjedan`.
  - Older → `Stariji`.
  - Each group preserves `updatedAt` DESC order.
  - Empty groups omitted from output.

```js
import { groupNotesByDate } from '../lib/grouping.js';

const day = 24 * 60 * 60 * 1000;
const now = new Date('2026-05-10T15:00:00Z').getTime();

test('pinned go to Pribadane regardless of age', () => {
  const notes = [
    { id: 'a', updatedAt: now - 365 * day, pinned: true },
    { id: 'b', updatedAt: now - 1 * day, pinned: false }
  ];
  const groups = groupNotesByDate(notes, now);
  expect(groups[0].label).toBe('Pribadane');
  expect(groups[0].notes.map(n => n.id)).toEqual(['a']);
});

test('group order is Pribadane, Danas, Jučer, Ovaj tjedan, Stariji', () => {
  const notes = [
    { id: 'p',  updatedAt: now,             pinned: true  },
    { id: 't1', updatedAt: now - 1 * 60_000, pinned: false },
    { id: 'y',  updatedAt: now - 1 * day,    pinned: false },
    { id: 'w',  updatedAt: now - 4 * day,    pinned: false },
    { id: 'o',  updatedAt: now - 30 * day,   pinned: false }
  ];
  const labels = groupNotesByDate(notes, now).map(g => g.label);
  expect(labels).toEqual(['Pribadane', 'Danas', 'Jučer', 'Ovaj tjedan', 'Stariji']);
});

test('empty groups omitted', () => {
  const notes = [{ id: 'x', updatedAt: now, pinned: false }];
  expect(groupNotesByDate(notes, now).map(g => g.label)).toEqual(['Danas']);
});
```

- [ ] **Step 2: Implement.** Use local-time date arithmetic — group buckets are based on the start-of-day in local time (so "today" rolls over at midnight in user's tz, not UTC).

```js
function startOfDay(t) {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function groupNotesByDate(notes, now = Date.now()) {
  const todayStart = startOfDay(now);
  const yStart = todayStart - 24 * 60 * 60 * 1000;
  const wStart = todayStart - 7 * 24 * 60 * 60 * 1000;

  const buckets = {
    Pribadane: [],
    Danas: [],
    'Jučer': [],
    'Ovaj tjedan': [],
    Stariji: []
  };

  for (const n of notes) {
    if (n.pinned) { buckets.Pribadane.push(n); continue; }
    if (n.updatedAt >= todayStart) buckets.Danas.push(n);
    else if (n.updatedAt >= yStart) buckets['Jučer'].push(n);
    else if (n.updatedAt >= wStart) buckets['Ovaj tjedan'].push(n);
    else buckets.Stariji.push(n);
  }

  const order = ['Pribadane', 'Danas', 'Jučer', 'Ovaj tjedan', 'Stariji'];
  return order
    .filter(k => buckets[k].length > 0)
    .map(k => ({
      label: k,
      notes: buckets[k].sort((a, b) => b.updatedAt - a.updatedAt)
    }));
}
```

- [ ] **Step 3: Commit.**

---

### Task B5: `lib/tags.js` — top-N tag derivation (TDD)

**Files:**
- Create: `firefox-notes-extension/lib/tags.js`
- Create: `firefox-notes-extension/tests/tags.test.js`

`derivedTagFilters(notes, top = 4)` returns an array starting with `'Sve'` followed by the top N most-used tag strings (case-insensitive count). Ties broken alphabetically.

- [ ] **Step 1: Failing test.**

```js
import { derivedTagFilters } from '../lib/tags.js';

test('returns Sve + top-4 by count desc, alpha tiebreak', () => {
  const notes = [
    { tags: ['posao', 'dev'] },
    { tags: ['posao', 'osobno'] },
    { tags: ['posao'] },
    { tags: ['dizajn', 'dev'] },
    { tags: [] }
  ];
  expect(derivedTagFilters(notes)).toEqual(['Sve', 'posao', 'dev', 'dizajn', 'osobno']);
});

test('handles missing or empty tag arrays', () => {
  expect(derivedTagFilters([])).toEqual(['Sve']);
  expect(derivedTagFilters([{}, { tags: undefined }])).toEqual(['Sve']);
});
```

- [ ] **Step 2: Implement.**

```js
export function derivedTagFilters(notes, top = 4) {
  const counts = new Map();
  for (const n of notes) {
    if (!Array.isArray(n.tags)) continue;
    for (const t of n.tags) counts.set(t, (counts.get(t) || 0) + 1);
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0].localeCompare(b[0]);
  });
  return ['Sve', ...sorted.slice(0, top).map(([t]) => t)];
}
```

- [ ] **Step 3: Commit.**

---

### Task B6: `lib/search.js` — text + query → highlighted runs (TDD)

**Files:**
- Create: `firefox-notes-extension/lib/search.js`
- Create: `firefox-notes-extension/tests/search.test.js`

`splitMatches(text, query)` returns an array of `{ text: string, hi: boolean }` runs, alternating non-match and match. Case-insensitive. Empty query returns `[{ text, hi: false }]`. Empty text returns `[]`.

- [ ] **Step 1: Failing tests** for: empty query → single non-hi run; one match in middle → 3 runs; multiple matches; case-insensitive; query that doesn't match → single non-hi run; empty text → empty array; regex meta chars in query are escaped.

- [ ] **Step 2: Implement.**

```js
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function splitMatches(text, query) {
  if (!text) return [];
  if (!query) return [{ text, hi: false }];
  const re = new RegExp(escapeRegex(query), 'gi');
  const out = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hi: false });
    out.push({ text: m[0], hi: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hi: false });
  return out;
}
```

- [ ] **Step 3: Commit.**

---

## Phase C — Popup launcher view

### Task C1: Popup HTML & CSS for launcher + new shells

**Files:**
- Modify: `firefox-notes-extension/popup/popup.html`
- Replace: `firefox-notes-extension/popup/popup.css`

- [ ] **Step 1: Replace popup.html** with the redesign markup. Three sibling `<section>` views inside `#app` toggled by `.hidden`:

```html
<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="UTF-8">
  <title>Bilješke</title>
  <link rel="stylesheet" href="tokens.css">
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <main id="app" class="b-popup">

    <!-- LAUNCHER VIEW -->
    <section id="view-launcher" class="view">
      <header class="lh-head">
        <h1>Bilješke</h1>
        <span id="launcher-stats" class="mono muted"></span>
      </header>
      <div class="lh-hero">
        <button id="hero-new" class="big" type="button">
          <span class="glyph" data-icon="plus"></span>
          <span class="copy">
            <span class="label">Nova bilješka</span>
            <span class="sub mono">Zalijepi tekst ili sliku</span>
          </span>
          <kbd class="kbd">⌘N</kbd>
        </button>
        <div class="row2">
          <button id="hero-list" class="sm" type="button">
            <span data-icon="list"></span>
            <span>Sve bilješke</span>
          </button>
          <button id="hero-tab" class="sm" type="button">
            <span data-icon="externalLink"></span>
            <span>Otvori karticu</span>
          </button>
        </div>
      </div>
      <h2 class="section-label mono">NEDAVNO</h2>
      <ul id="launcher-recents" class="recent-list"></ul>
    </section>

    <!-- LIST VIEW -->
    <section id="view-list" class="view hidden">
      <header class="bar">
        <div class="bar-titles">
          <h1>Bilješke</h1>
          <span id="list-substats" class="mono muted">— bilješki · auto-spremanje</span>
        </div>
        <button id="btn-new" class="btn primary" type="button"><span data-icon="plus"></span> Nova</button>
      </header>
      <div class="search-row">
        <span class="search-icon" data-icon="search"></span>
        <input id="search" type="search" placeholder="Pretraži bilješke…" autocomplete="off">
      </div>
      <div id="note-list" class="note-list"></div>
      <p id="empty-list" class="empty hidden">
        <span class="empty-icon" data-icon="bracket"></span>
        <span class="empty-title">Nema bilješki</span>
        <span class="empty-sub">Zalijepi tekst ili sliku za novu</span>
      </p>
    </section>

    <!-- EDITOR VIEW -->
    <section id="view-editor" class="view hidden">
      <header class="bar editor-bar">
        <button id="btn-back" class="btn ghost" type="button">← Natrag</button>
        <div class="save-state mono muted" id="save-state">
          <span class="dot"></span><span class="label">Spremljeno</span>
        </div>
        <button id="btn-more" class="btn ghost icon" type="button" data-icon="more" aria-label="Više"></button>
        <button id="btn-delete" class="btn ghost danger icon" type="button" data-icon="trash" aria-label="Obriši"></button>
      </header>
      <textarea id="editor-body" placeholder="Bilješka…"></textarea>
      <footer class="att-foot" id="att-foot">
        <span class="section-label mono"><span class="att-count-label">PRIVITCI</span></span>
        <div id="attachment-list" class="att-chips"></div>
        <button id="btn-add-att" class="btn ghost" type="button">+ Dodaj</button>
        <input id="file-input" type="file" accept="image/*,application/pdf" hidden>
      </footer>
    </section>

    <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>

    <div id="modal" class="modal hidden">
      <img id="modal-img" alt="Pregled privitka">
    </div>
  </main>
  <script type="module" src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Replace popup.css** with the redesigned styles. Keep it under 600 lines. Source the canonical visual rules from `design_files/styles.css` — copy the relevant blocks (`body.b-popup`, `.lh-head`, `.lh-hero`, `.b-row`, `.btn`, `.search-row`, `.att-foot`, `.toast`, `.modal`, `.empty`, `.section-label`, `.save-state`) directly. Strip rules for classes that don't map to our DOM. Use `var(--token)` references defined in `tokens.css`.

  Add these specific rules at the bottom of `popup.css` (Firefox popup renders without dark mode UA; force light tokens):

  ```css
  body { width: 380px; min-height: 560px; max-height: 600px; background: var(--card); color: var(--ink); font-family: var(--font); font-size: 13px; margin: 0; }
  [data-icon] { display: inline-flex; vertical-align: middle; }
  ```

  Also: add a `populate-icons.js`-style helper… actually, do this in `popup.js` step (Task C2): query all `[data-icon]` and inject `iconHtml(name)`.

- [ ] **Step 3: Commit (HTML + CSS).** No test impact yet.

```bash
git add firefox-notes-extension/popup/popup.html firefox-notes-extension/popup/popup.css
git commit -m "feat(notes-ext): redesigned popup html+css with launcher view"
```

---

### Task C2: popup.js view-state machine + icon injection

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Add view state** — `state.view: 'launcher' | 'list' | 'editor'`. Default `'launcher'`.

- [ ] **Step 2: Add `setView(name)`** that toggles `.hidden` on the three view sections and updates `state.view`.

- [ ] **Step 3: Add icon injection** at startup:

```js
import { iconHtml } from './icons.js';

function injectIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]')) {
    const name = el.dataset.icon;
    if (name) el.innerHTML = iconHtml(name);
  }
}
```

Call `injectIcons()` once at the end of `init()`.

- [ ] **Step 4: Wire launcher buttons:**

```js
async function renderLauncher() {
  const notes = await listNotes(state.db);
  $('#launcher-stats').textContent = `${notes.length} bilješki`;
  const recents = notes.slice(0, 4);
  const ul = $('#launcher-recents');
  ul.innerHTML = '';
  for (const n of recents) {
    const li = document.createElement('li');
    li.className = 'recent';
    li.innerHTML = `
      <span class="thumb" data-icon="${n.attachmentIds.length ? 'image' : 'list'}"></span>
      <span class="preview">${escapeHtml(notePreview(n))}</span>
      <span class="age mono muted">${formatAge(Date.now() - n.updatedAt)}</span>
    `;
    li.addEventListener('click', () => openEditor(n.id));
    ul.appendChild(li);
  }
  injectIcons(ul);
}

$('#hero-new').addEventListener('click', async () => {
  const note = await createNote(state.db);
  openEditor(note.id);
});
$('#hero-list').addEventListener('click', () => setView('list'));
$('#hero-tab').addEventListener('click', async () => {
  // browser is browser-extension global; available in popup context
  await browser.tabs.create({ url: browser.runtime.getURL('tab/tab.html') });
  window.close();
});
```

`notePreview(n)` returns `n.body.slice(0, 80)` (or `''`). `formatAge(ms)` returns `4m`, `2h`, `1d`, etc. Implement both as helpers near the top of `popup.js`.

- [ ] **Step 5: Update init():**

```js
async function init() {
  state.db = await openDb();
  injectIcons();
  bindStaticEvents();
  bindPasteHandler();
  await renderLauncher();
  setView('launcher');
}
```

- [ ] **Step 6: Update `setView`** so it also calls `renderLauncher` / `renderList` as appropriate.

- [ ] **Step 7: Update `showList`** to call `setView('list')` and `renderList()`. Update `openEditor` to call `setView('editor')`.

- [ ] **Step 8: Manual smoke verify** in Firefox: launcher renders first, hero opens editor, list link works, recents click works, "Otvori karticu" attempts to open tab.html (will 404 until Phase F — accept this, it'll be wired then).

- [ ] **Step 9: Tests stay green. Commit.**

---

## Phase D — Popup list redesign

### Task D1: New list row template + date grouping

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`

- [ ] **Step 1: Replace `renderList`** to:
  1. Fetch notes via `listNotes` or `searchNotes`.
  2. Group via `groupNotesByDate(notes)` from `lib/grouping.js`.
  3. Render group headers + rows using the new `.b-row` template (no title; thumbnail; preview; mono meta line; age + paperclip pill).

```js
import { groupNotesByDate } from '../lib/grouping.js';
import { getAttachment } from '../lib/notes.js';

async function renderList() {
  const allNotes = state.searchQuery
    ? await searchNotes(state.db, state.searchQuery)
    : await listNotes(state.db);

  const container = $('#note-list');
  container.innerHTML = '';

  if (allNotes.length === 0) {
    $('#empty-list').classList.remove('hidden');
    container.classList.add('hidden');
    return;
  }
  $('#empty-list').classList.add('hidden');
  container.classList.remove('hidden');

  $('#list-substats').textContent = `${allNotes.length} bilješki · auto-spremanje`;

  const groups = groupNotesByDate(allNotes);
  for (const group of groups) {
    const head = document.createElement('div');
    head.className = 'group-head';
    head.innerHTML = `<span class="section-label mono">${group.label}</span><span class="mono muted">${group.notes.length}</span>`;
    container.appendChild(head);
    for (const note of group.notes) {
      container.appendChild(await buildNoteRow(note));
    }
  }
  injectIcons(container);
}

async function buildNoteRow(note) {
  const li = document.createElement('div');
  li.className = 'b-row';
  li.dataset.id = note.id;

  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  // First image attachment thumbnail if present
  const firstImg = await firstImageAttachment(note);
  if (firstImg && firstImg.thumbBlob) {
    const url = URL.createObjectURL(firstImg.thumbBlob);
    objectUrls.set(`row-${note.id}`, url);
    thumb.innerHTML = `<img src="${url}" alt="">`;
  } else if (note.attachmentIds.length) {
    thumb.innerHTML = `<span data-icon="image"></span>`;
  } else {
    thumb.innerHTML = `<span data-icon="list"></span>`;
  }

  const body = document.createElement('div');
  body.className = 'body';
  body.innerHTML = `
    <div class="preview">${escapeHtml(notePreview(note)) || '<em class="muted">(prazna bilješka)</em>'}</div>
    <div class="meta mono muted">
      ${formatAge(Date.now() - note.updatedAt)} · ${note.body.length} zn.
    </div>
  `;

  const right = document.createElement('div');
  right.className = 'right';
  right.innerHTML = `
    <span class="age mono muted">${formatAge(Date.now() - note.updatedAt)}</span>
    ${note.attachmentIds.length ? `<span class="att-pill mono"><span data-icon="paperclip"></span> ${note.attachmentIds.length}</span>` : ''}
  `;

  li.append(thumb, body, right);
  li.addEventListener('click', () => openEditor(note.id));
  return li;
}

async function firstImageAttachment(note) {
  for (const id of note.attachmentIds) {
    const a = await getAttachment(state.db, id);
    if (a && a.mimeType && a.mimeType.startsWith('image/')) return a;
  }
  return null;
}
```

- [ ] **Step 2: Update CSS** in `popup.css` — ensure `.b-row`, `.b-row .thumb`, `.b-row .body .preview`, `.b-row .body .meta`, `.b-row .right .age`, `.b-row .right .att-pill`, `.group-head` are styled per spec. Source from `design_files/styles.css`.

- [ ] **Step 3: Object URL cleanup** — extend the existing `showList`/`onDeleteNoteClick` cleanup to also iterate `row-*` keys.

- [ ] **Step 4: Manual smoke** — list renders with date groups, thumbnails for image attachments, paperclip pill for note with attachments.

- [ ] **Step 5: Commit.**

---

### Task D2: Editor redesign (top bar with save state, single textarea, attachment chip footer)

**Files:**
- Modify: `firefox-notes-extension/popup/popup.js`
- Modify: `firefox-notes-extension/popup/popup.css`

- [ ] **Step 1: Remove the title input** path since the new design has no title field. Confirm `editor-title` references in popup.js are dropped (the HTML in Task C1 already removed it).
  - `openEditor` no longer sets `$('#editor-title').value`.
  - `flushAndPrune` no longer flushes title.
  - `unbindEditorEvents` only nulls body's `oninput`.

- [ ] **Step 2: Save state pulse.** Add `state.saveState: 'idle' | 'saving' | 'saved' | 'error'`. After each successful `updateNote`, set `'saved'` and pulse the dot for 1.2s, then leave it lit. After 30 s without edits, the label re-renders from "Spremljeno · just now" to "Spremljeno · 30s ago" — implement a single `setInterval(updateSaveAge, 30_000)` that re-renders the save-state label only.

  Add `function renderSaveState()`:

  ```js
  function renderSaveState() {
    const el = $('#save-state');
    if (!el) return;
    if (state.saveState === 'saving') {
      el.innerHTML = `<span class="label">Sprema se…</span>`;
      el.className = 'save-state mono muted';
    } else if (state.saveState === 'error') {
      el.innerHTML = `<span class="dot error"></span><span class="label">Greška spremanja</span>`;
      el.className = 'save-state mono error';
    } else {
      el.innerHTML = `<span class="dot"></span><span class="label">Spremljeno · ${formatAge(Date.now() - state.lastSavedAt)}</span>`;
      el.className = 'save-state mono muted';
    }
  }
  ```

  Hook into `flushBody`, `onTitleBlur` (deleted but autosave on body still calls), and the existing autosave call sites to update `state.saveState` and `state.lastSavedAt`.

- [ ] **Step 3: Attachment chip footer.** Replace the previous `attachment-list` row layout. Each chip:

  ```html
  <div class="att-chip">
    <span class="swatch"><img src="${thumbUrl}"></span>  <!-- or generic doc icon -->
    <span class="name mono muted">${filename}</span>
    <button class="ax" type="button" data-icon="x"></button>
  </div>
  ```

  Update `renderAttachmentRow` to fill chip-style layout. Use `att.thumbBlob` URL when available, else original `att.blob` URL.

- [ ] **Step 4: `+ Dodaj` button.** Wire `#btn-add-att` to trigger the hidden `#file-input`, and `#file-input.change` to read selected files and pass them through `addAttachment` (same code path as paste).

  ```js
  $('#btn-add-att').addEventListener('click', () => $('#file-input').click());
  $('#file-input').addEventListener('change', async (e) => {
    const files = Array.from(e.target.files || []);
    for (const f of files) {
      try {
        const att = await addAttachment(state.db, state.currentNoteId, f, f.type, f.name);
        showToast(`${f.name} dodan`);
      } catch (err) { showToast('Greška pri dodavanju datoteke', 'error'); }
    }
    e.target.value = '';
    const note = await getNote(state.db, state.currentNoteId);
    if (note) renderAttachments(note);
  });
  ```

- [ ] **Step 5: Manual smoke** — open editor, type → save state pulses → after 30s shows "Spremljeno · 30s". Paste image → chip shows real thumbnail. + Dodaj → file picker → file appears as chip.

- [ ] **Step 6: Commit.**

---

## Phase E — Tab page (rich mode)

### Task E1: Tab scaffold (HTML + CSS + JS shell)

**Files:**
- Create: `firefox-notes-extension/tab/tab.html`
- Create: `firefox-notes-extension/tab/tab.css`
- Create: `firefox-notes-extension/tab/tab.js`
- Modify: `firefox-notes-extension/manifest.json` — add `web_accessible_resources` entry if Firefox requires it for `runtime.getURL` of the tab page (it does NOT for own-extension navigation, but check).

- [ ] **Step 1: tab.html** — three-column shell:

```html
<!DOCTYPE html>
<html lang="hr">
<head>
  <meta charset="UTF-8">
  <title>Bilješke</title>
  <link rel="stylesheet" href="../popup/tokens.css">
  <link rel="stylesheet" href="tab.css">
</head>
<body>
  <div class="tb-app">
    <aside class="tb-side">
      <div class="head">
        <div class="brand">
          <span class="badge" data-icon="bracket"></span>
          <h1>Bilješke</h1>
          <span id="side-count" class="mono muted"></span>
        </div>
        <div class="actions">
          <button id="side-new" class="btn primary" type="button"><span data-icon="plus"></span> Nova</button>
          <button id="side-filter" class="btn" type="button">Filtri</button>
        </div>
        <div class="search-row">
          <span data-icon="search"></span>
          <input id="side-search" type="search" placeholder="Pretraži (⌘K)…" autocomplete="off">
        </div>
      </div>
      <div class="filters" id="side-filters"></div>
      <div class="scroll" id="side-list"></div>
    </aside>

    <main class="tb-main">
      <header class="crumbs">
        <div class="left">
          <span data-icon="list"></span>
          <span class="path mono muted" id="crumb-path">Bilješke</span>
        </div>
        <div class="right">
          <button id="toggle-search" class="btn ghost" type="button">Pretraži u bilješci</button>
          <button id="toggle-pin" class="btn ghost icon" type="button" data-icon="pin" aria-label="Pribadač"></button>
          <button class="btn ghost icon" type="button" data-icon="more" aria-label="Više"></button>
        </div>
      </header>
      <article class="doc" id="doc">
        <div class="empty muted">Odaberi bilješku iz lijevog popisa.</div>
      </article>
      <footer class="tb-foot mono muted" id="tb-foot">
        <span id="foot-save"></span>
        <span class="sep"></span>
        <span id="foot-chars"></span>
        <span class="sep"></span>
        <span id="foot-atts"></span>
        <span style="margin-left:auto"></span>
        <span class="hint">⌘K Pretraži</span>
        <span class="sep"></span>
        <span class="hint">⌘N Nova</span>
        <span class="sep"></span>
        <span class="hint">⌘? Prečaci</span>
      </footer>
    </main>

    <aside class="tb-right" id="tb-right">
      <section class="panel">
        <h3 class="section-label mono">PRIVITCI <span id="right-att-count" class="mono muted"></span></h3>
        <div class="att-grid" id="att-grid"></div>
      </section>
      <section class="panel">
        <h3 class="section-label mono">DETALJI</h3>
        <dl id="details"></dl>
      </section>
      <section class="panel">
        <h3 class="section-label mono">OZNAKE</h3>
        <div class="tags" id="tags"></div>
      </section>
      <section class="panel actions-panel">
        <h3 class="section-label mono">BRZE AKCIJE</h3>
        <button class="btn ghost" id="act-export" type="button"><span data-icon="download"></span> Izvezi bilješku</button>
        <button class="btn ghost" id="act-pin" type="button"><span data-icon="pin"></span> Pribadač</button>
        <button class="btn ghost danger" id="act-delete" type="button"><span data-icon="trash"></span> Obriši</button>
      </section>
    </aside>
  </div>

  <div id="modal-shortcuts" class="modal hidden"></div>
  <div id="modal-export" class="modal hidden"></div>
  <div id="toast" class="toast hidden" role="status" aria-live="polite"></div>

  <script type="module" src="tab.js"></script>
</body>
</html>
```

- [ ] **Step 2: tab.css** — copy the relevant `.tb-app`, `.tb-side`, `.tb-main`, `.tb-right`, `.crumbs`, `.doc`, `.tb-foot`, `.panel`, `.att-grid`, `.tags` rules from `design_files/styles.css`. Use `var(--token)` references.

- [ ] **Step 3: tab.js shell** — minimal:

```js
import { openDb } from '../lib/db.js';
import { listNotes, getNote, createNote, updateNote, deleteNote, togglePin, setTags, addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { groupNotesByDate } from '../lib/grouping.js';
import { derivedTagFilters } from '../lib/tags.js';
import { splitMatches } from '../lib/search.js';
import { iconHtml } from '../popup/icons.js';

const $ = (sel) => document.querySelector(sel);
const state = {
  db: null,
  activeNoteId: null,
  search: '',
  searchInDoc: false,
  filterTag: 'Sve',
  notes: []
};

async function init() {
  state.db = await openDb();
  injectIcons();
  await refreshNotes();
  renderSidebar();
  bindEvents();
}

async function refreshNotes() {
  state.notes = await listNotes(state.db);
}

function injectIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]')) {
    el.innerHTML = iconHtml(el.dataset.icon);
  }
}

function renderSidebar() { /* implemented in Task E2 */ }
function bindEvents() { /* implemented in Task E2 */ }

init().catch(err => {
  console.error('[notes] tab init', err);
  document.body.innerHTML = '<div style="padding:24px">Ne mogu otvoriti pohranu.</div>';
});
```

- [ ] **Step 4: Verify load** — open `tab/tab.html` directly (file://) in Firefox to confirm CSS loads and shell renders. Note: extension APIs (`browser.runtime.getURL`) won't work in file:// — that's fine, we only access them when launched from the extension. For the proper test, install via `about:debugging` and open the popup → "Otvori karticu".

- [ ] **Step 5: Commit.**

---

### Task E2: Tab sidebar — list + filters + search

**Files:**
- Modify: `firefox-notes-extension/tab/tab.js`

- [ ] **Step 1: `renderSidebar`**

  ```js
  function renderSidebar() {
    $('#side-count').textContent = `${state.notes.length} bilješki`;
    renderFilters();
    renderSidebarList();
  }
  function renderFilters() {
    const tags = derivedTagFilters(state.notes, 4);
    const div = $('#side-filters');
    div.innerHTML = '';
    for (const t of tags) {
      const chip = document.createElement('button');
      chip.className = 'chip mono' + (state.filterTag === t ? ' active' : '');
      chip.textContent = t === 'Sve' ? 'Sve' : t;
      chip.addEventListener('click', () => { state.filterTag = t; renderSidebar(); });
      div.appendChild(chip);
    }
  }
  function renderSidebarList() {
    const filtered = state.notes.filter(n => {
      if (state.filterTag !== 'Sve' && !(n.tags || []).includes(state.filterTag)) return false;
      if (state.search && !n.body.toLowerCase().includes(state.search.toLowerCase())) return false;
      return true;
    });
    const ul = $('#side-list');
    ul.innerHTML = '';
    const groups = groupNotesByDate(filtered);
    for (const g of groups) {
      const h = document.createElement('div');
      h.className = 'group-head';
      h.innerHTML = `<span class="section-label mono">${g.label}</span><span class="mono muted">${g.notes.length}</span>`;
      ul.appendChild(h);
      for (const n of g.notes) ul.appendChild(buildSidebarRow(n));
    }
  }
  function buildSidebarRow(n) { /* same shape as popup .b-row but slimmer */ }
  ```

- [ ] **Step 2: `bindEvents`**

  ```js
  function bindEvents() {
    $('#side-new').addEventListener('click', async () => {
      const note = await createNote(state.db);
      await refreshNotes();
      openNote(note.id);
      renderSidebar();
    });
    $('#side-search').addEventListener('input', (e) => { state.search = e.target.value; renderSidebar(); });

    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); $('#side-search').focus(); }
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') { e.preventDefault(); $('#side-new').click(); }
      if ((e.metaKey || e.ctrlKey) && e.key === '/') { e.preventDefault(); openShortcuts(); }
      if ((e.metaKey || e.ctrlKey) && e.key === '?') { e.preventDefault(); openShortcuts(); }
      if (e.key === 'Escape') { /* clear active note focus */ }
    });
  }
  ```

- [ ] **Step 3: Commit.**

---

### Task E3: Tab editor — document render + crumbs + footer

**Files:**
- Modify: `firefox-notes-extension/tab/tab.js`
- Modify: `firefox-notes-extension/tab/tab.css`

- [ ] **Step 1: `openNote(id)` and `renderDoc(note)`**:

  Header crumbs render `Bilješke / {first 32 chars of body}…` in mono. Document area:
  - Meta line: `Uređeno {age}` + tag pills + `{N} znakova · {paragraphs} odlomaka`.
  - Body rendered via `splitMatches(note.body, state.searchInDoc ? state.search : '')` mapping each run to `<span>` or `<mark>` for highlighting.
  - Inline attachment cards (as described in README §5 center column point 2) inserted at end (or at attachment-marker positions if you want; for MVP, render after body).

  Make `renderDoc` editable: clicking the body switches it to a `<textarea>` (or use `contenteditable` on a `<pre>` styled to look like the read mode). Simplest path: keep an `<textarea>` always, styled to look like the read mode — fits MVP and matches popup behaviour.

  ```html
  <article class="doc">
    <div class="meta-line mono muted">Uređeno 4m · ...</div>
    <textarea class="body-textarea">{body}</textarea>
    <div class="inline-atts"><!-- attachment cards --></div>
  </article>
  ```

  When `searchInDoc` is on, render an overlay `<div>` with `<mark>` runs absolutely positioned over the textarea (or use a parallel `<pre>` mirror). For simpler MVP: hide the textarea, show a `<pre>` with marked spans, and re-show textarea on click.

- [ ] **Step 2: Footer state.** `#foot-save`, `#foot-chars`, `#foot-atts` populated from active note.

- [ ] **Step 3: Manual verify** in tab. Commit.

---

### Task E4: Tab right column — attachments grid, details, tags, actions

**Files:**
- Modify: `firefox-notes-extension/tab/tab.js`
- Modify: `firefox-notes-extension/tab/tab.css`

- [ ] **Step 1: `renderRight(note)`** — populate the 4 panels.

  - **Privitci** — 2-col grid of cards. Each card uses `att.thumbBlob` for image preview, doc icon for non-image. Last cell is a dashed `+ Zalijepi` card that triggers the same file picker / paste flow.
  - **Detalji** — populate `dl` with rows: `ID` (mono short hash: first 4 chars + last 4 of `note.id`), `Stvoreno`, `Uređeno`, `Veličina` (sum of attachment sizes + body length), `Verzija` (always `1` for MVP).
  - **Oznake** — pill list of `note.tags` + a dashed `+ oznaka` chip that triggers `prompt('Nova oznaka:')`. Submit calls `setTags(db, id, [...note.tags, newTag])` and re-renders.
  - **Brze akcije** — hook `#act-export` → open export modal (Phase G), `#act-pin` → `togglePin`, `#act-delete` → confirm + `deleteNote`.

- [ ] **Step 2: Wire the popup's "Otvori karticu" link** (already present from Task C2 step 4) — verify after this task that opening tab from popup navigates to the existing note id is NOT a requirement (MVP: tab opens with no active note; user picks from sidebar).

- [ ] **Step 3: Commit.**

---

## Phase F — In-document search highlights

### Task F1: `searchInDoc` toggle and step-through

**Files:**
- Modify: `firefox-notes-extension/tab/tab.js`

- [ ] **Step 1: `#toggle-search` button** flips `state.searchInDoc`. When on, the document switches to read-mode (`<pre>` with `<mark>`s); when off, back to `<textarea>`.

- [ ] **Step 2: ↑/↓ when `searchInDoc`** — track current match index, scroll `<mark>` elements into view. Bind:

  ```js
  document.addEventListener('keydown', (e) => {
    if (!state.searchInDoc) return;
    if (e.key === 'ArrowDown') { stepMatch(+1); e.preventDefault(); }
    if (e.key === 'ArrowUp')   { stepMatch(-1); e.preventDefault(); }
  });
  ```

- [ ] **Step 3: Commit.**

---

## Phase G — Shortcuts & Export modals

### Task G1: Shortcuts modal

**Files:**
- Modify: `firefox-notes-extension/tab/tab.js`
- Modify: `firefox-notes-extension/tab/tab.css`

- [ ] **Step 1: `openShortcuts()` populates `#modal-shortcuts`** with the README §6 markup. Three sections (Globalno, Lista, Editor); each row is `<label>` + `<kbd class="k">` chips. Close on backdrop click or Esc.

- [ ] **Step 2: Bind `⌘?` and `⌘/`** (already bound in Task E2). Make sure modal closes correctly.

- [ ] **Step 3: Commit.**

---

### Task G2: Export modal — .md and .json

**Files:**
- Create: `firefox-notes-extension/lib/export.js`
- Create: `firefox-notes-extension/tests/export.test.js`
- Modify: `firefox-notes-extension/tab/tab.js`

- [ ] **Step 1: TDD `lib/export.js`.** Tests:
  - `exportMarkdown(notes)` returns a Blob whose text is the concatenation of one `--- frontmatter --- \n body\n\n---\n` block per note. Frontmatter includes `id, createdAt, updatedAt, tags, attachments[]` (filenames only, since attachments aren't embedded in md).
  - `exportJson(notes, attachmentsByNoteId)` returns a Blob containing valid JSON with `{ notes: [...], attachments: [{ noteId, id, mimeType, filename, size, dataBase64 }] }`. Uses `FileReader.readAsDataURL` for base64. (Stub `FileReader` in tests if missing; jsdom has it.)

- [ ] **Step 2: Implement.**

  ```js
  function frontmatter(note) {
    return [
      '---',
      `id: ${note.id}`,
      `createdAt: ${new Date(note.createdAt).toISOString()}`,
      `updatedAt: ${new Date(note.updatedAt).toISOString()}`,
      `tags: [${(note.tags || []).map(t => `"${t}"`).join(', ')}]`,
      `attachments: [${note.attachmentIds.map(a => `"${a}"`).join(', ')}]`,
      '---',
      ''
    ].join('\n');
  }

  export function exportMarkdown(notes) {
    const text = notes.map(n => frontmatter(n) + n.body + '\n').join('\n\n---\n\n');
    return new Blob([text], { type: 'text/markdown' });
  }

  export async function exportJson(notes, attachmentsByNoteId) {
    const flatAtts = [];
    for (const [noteId, atts] of Object.entries(attachmentsByNoteId)) {
      for (const a of atts) {
        flatAtts.push({
          noteId,
          id: a.id,
          mimeType: a.mimeType,
          filename: a.filename,
          size: a.size,
          dataBase64: await blobToBase64(a.blob)
        });
      }
    }
    const payload = { notes, attachments: flatAtts };
    return new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const dataUrl = fr.result;
        const idx = dataUrl.indexOf(',');
        resolve(idx >= 0 ? dataUrl.slice(idx + 1) : '');
      };
      fr.onerror = () => reject(fr.error);
      fr.readAsDataURL(blob);
    });
  }
  ```

- [ ] **Step 3: Wire export modal** in `tab.js`. Three format cards. The `Preuzmi` button calls the right serialiser, then triggers download via `a.download` link.

- [ ] **Step 4: Commit.**

---

### Task G3: ZIP export (vendor JSZip)

**Files:**
- Create: `firefox-notes-extension/lib/vendor/jszip.min.js`
- Modify: `firefox-notes-extension/lib/export.js`
- Modify: `firefox-notes-extension/tests/export.test.js`

- [ ] **Step 1: Vendor JSZip.** Download `jszip.min.js` (latest stable, ~93 KB). Place at `lib/vendor/jszip.min.js`. Use the standalone build that exposes `JSZip` as global or via UMD; we'll import it dynamically:

  ```js
  async function loadJSZip() {
    const m = await import(browser.runtime.getURL('lib/vendor/jszip.min.js'));
    return m.default || globalThis.JSZip;
  }
  ```

  In tests, the dynamic import path won't work — guard with feature-detection: if loading fails, throw "ZIP export not available in this environment" and skip the test.

- [ ] **Step 2: Implement `exportZip(notes, attachments)`** — markdown files at root, attachments under `attachments/{noteId}/{filename}`.

- [ ] **Step 3: Test (skipped in jsdom)** marked with `it.skip` plus a comment explaining the runtime requirement.

- [ ] **Step 4: Wire third format card. Commit.**

---

## Phase H — Polish & manual verification

### Task H1: Toast & save state across views

- [ ] Verify the toast surfaces work in both popup and tab. Same CSS, same DOM id (`#toast`).

### Task H2: Object URL audit

- [ ] Audit all `URL.createObjectURL` call sites (rows, chips, attachment grid, modal preview). Each must have a corresponding `revokeObjectURL` on view unmount or note change. Add a `releaseAllObjectUrls()` helper that walks the `objectUrls` Map and clears it.

### Task H3: Keyboard shortcuts wiring (full set)

- [ ] All shortcuts from README §6 wired in tab.js:
  - `⌘N` → new note
  - `⌘K` → focus search
  - `⌘?`/`⌘/` → shortcuts modal
  - `⌘S` → flush body autosave (debounced may not have fired yet)
  - `Esc` → close modal or unfocus textarea
  - List: `↑/↓`/`↵`/`⌘⌫`/`P`

### Task H4: Manual smoke test (deferred to user)

The user must verify visually in Firefox:
1. Toolbar shows the bracket icon.
2. Popup launches into launcher view; "+ Nova" creates note + opens editor.
3. List view shows date-grouped rows with thumbnails.
4. Editor shows save state pulse; ⌘N creates new note.
5. "Otvori karticu" opens `tab.html`; left+center+right columns render.
6. Sidebar filter chips reflect actual top-tags (or "Sve" only if no tags exist).
7. ⌘? opens shortcuts modal; ⌘K focuses sidebar search.
8. "Izvezi bilješku" opens export modal; .md and .json downloads work; .zip works once vendored.
9. Pin a note → moves to "Pribadane" group at top.
10. Add a tag via the right inspector → appears as pill, also flows into sidebar filter chips.

---

## Out of scope (per handoff §"Out of scope")

- Dark mode.
- Markdown rendering.
- Backlinks.
- Multi-device sync.
- Separate title field — confirmed product decision.
- Global ⌘N hotkey via `commands` permission (per user's decision).

---

## Test counts (target after each phase)

| Phase | New tests |
|-------|-----------|
| Phase A (no tests) | 29 (unchanged) |
| B1 (pin/tags) | 32 |
| B2 (thumbnail) | 35 |
| B3 (attach thumbs) | 36 |
| B4 (grouping) | 39 |
| B5 (tags helper) | 41 |
| B6 (search) | 47 |
| C–F (UI; no new tests by default) | 47 |
| G2 (export md/json) | 51 |
| G3 (export zip — skip) | 51 |

If a UI task uncovers a logic bug, write a regression test in the appropriate `lib/` test file.
