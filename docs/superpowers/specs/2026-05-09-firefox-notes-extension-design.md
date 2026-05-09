# Firefox Notes Extension — Design Spec

**Status**: Draft for implementation
**Date**: 2026-05-09
**Scope**: MVP — standalone Firefox extension for personal note-taking with text and clipboard-pasted images.

## Goals

- Lightweight personal notepad available from the Firefox toolbar
- Text body + image attachments per note
- Paste from clipboard (Ctrl+V) attaches images — primary use case is OS screenshots
- Local-only storage; no cloud, no MCP, no third-party services
- No build pipeline — vanilla JS only

## Non-Goals (MVP)

- Syncing across devices
- Export / import (JSON, Markdown)
- URL-linked notes (notes are global, not per-page)
- Tags, folders, colors, pinning
- Rich text / mixed inline content (text-only body + attachments listed below)
- Drag-and-drop image upload (only paste)
- Cloud or MCP integration
- E2E browser tests

## Architecture

### Approach

Vanilla JS + IndexedDB + Manifest V3.

Three layers, separated by concern:

| Layer | Purpose | Knows about |
|---|---|---|
| `lib/db.js` | IndexedDB primitives (open, get, put, delete, list, transactions) | IndexedDB only |
| `lib/notes.js` | Domain logic (Note, Attachment, CRUD, cascade delete) | Domain model + db.js |
| `popup/popup.js` | UI rendering, event handlers, view switching | DOM + notes.js |

Rationale: domain logic can be unit-tested with a mock DB; storage backend can be swapped without touching UI.

### File layout

```
firefox-notes-extension/
├── manifest.json
├── icons/
│   ├── icon-48.png
│   └── icon-96.png
├── popup/
│   ├── popup.html
│   ├── popup.css
│   └── popup.js
├── lib/
│   ├── db.js
│   ├── notes.js
│   └── clipboard.js
├── tests/
│   ├── db.test.js
│   └── notes.test.js
└── package.json          # dev deps only (jest, fake-indexeddb)
```

## Manifest

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

- No `permissions` declared — IndexedDB and `paste` events on user-initiated actions need none.
- No content scripts — extension does not interact with web pages.
- No background service worker — all logic runs in the popup while it is open.
- `gecko.id` required for stable identification (temp install + future signing).
- `strict_min_version: "115.0"` — Firefox ESR baseline; covers MV3, `crypto.randomUUID()`, all APIs used.

## Data Model

**Database**: `firefox-notes-db`, version 1.

### Object store: `notes` (keyPath: `id`)

```js
{
  id: "uuid-v4-string",          // crypto.randomUUID()
  title: "string",                // user-entered, capped at 200 chars in UI
  body: "string",                 // plain text
  attachmentIds: ["uuid", ...],  // references into attachments store
  createdAt: 1714000000000,       // Date.now()
  updatedAt: 1714000050000
}
```

**Index**: `updatedAt` — used to sort the list view (most recently edited first).

### Object store: `attachments` (keyPath: `id`)

```js
{
  id: "uuid-v4-string",
  blob: Blob,                     // raw image bytes (binary)
  mimeType: "image/png",          // from clipboard item.type
  filename: "screenshot-20260509-143022.png",
  size: 142000                    // bytes
}
```

### Cascade delete

`notes.deleteNote(id)` opens a single read-write transaction over both stores: deletes the note record and every attachment whose ID is in the note's `attachmentIds`. Atomic — if the transaction aborts, nothing is deleted. Avoids orphan attachments.

### Quota

IndexedDB has a per-origin quota of roughly 50% of free disk space — far more than `storage.local`'s ~5 MB. No code-level size cap on individual notes. A single attachment is rejected if larger than 50 MB (popup render becomes sluggish above this).

## UI

Popup window, ~400×600 px. Two views in the same document, swapped by toggling visibility. No router, no SPA framework.

### View 1 — List (default)

```
┌────────────────────────────────────────┐
│  Bilješke                  [+ Nova]    │
├────────────────────────────────────────┤
│  🔍 Pretraži bilješke...               │
├────────────────────────────────────────┤
│  ┌──────────────────────────────────┐  │
│  │ Sastanak s timom         🖼 2    │  │
│  │ Razgovarali smo o roadmapu...    │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │ Ideja za feature                 │  │
│  │ Ako bi se moglo dodati...        │  │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

- Sorted DESC by `updatedAt`
- Each card shows title, body preview (1–2 lines), attachment count
- Click card → open editor for that note
- `+ Nova` → open editor for a new (empty) note
- Search input filters the list client-side on title + body (case-insensitive substring); fast for the expected ≤ 1000 notes

### View 2 — Editor

```
┌────────────────────────────────────────┐
│  ← Natrag                  [Obriši]    │
├────────────────────────────────────────┤
│  ┌──────────────────────────────────┐  │
│  │ Naslov...                        │  │
│  └──────────────────────────────────┘  │
│  ┌──────────────────────────────────┐  │
│  │                                  │  │
│  │ Tekst bilješke...                │  │
│  │                                  │  │
│  └──────────────────────────────────┘  │
│  ┌─Privitci──────────────────────────┐ │
│  │ [thumb] screenshot1.png   [✕]    │ │
│  │ [thumb] screenshot2.png   [✕]    │ │
│  └──────────────────────────────────┘  │
└────────────────────────────────────────┘
```

- **Auto-save**: title saves on blur; body saves with a 500 ms debounce. No Save button.
- **Flush on exit**: when navigating away (← Natrag) or on `pagehide` (popup closes), any pending debounced save is flushed synchronously before the navigation/cleanup. Ensures the last keystroke is never lost.
- **Empty-note pruning**: after the flush above, if the note has no title, no body, and no attachments, it is deleted instead of saved. Avoids accumulating empties.
- **Delete confirmation**: "Obriši" prompts before deleting (cascade includes attachments).
- **Attachment thumbs**: clicking a thumbnail opens it in a modal overlay at full size; ✕ removes the attachment after confirmation.

## Paste Flow

The defining feature: Ctrl+V into the body textarea attaches a clipboard image rather than pasting base64.

```js
textarea.addEventListener('paste', async (e) => {
  for (const item of e.clipboardData.items) {
    if (item.type.startsWith('image/')) {
      e.preventDefault();
      const blob = item.getAsFile();
      await addAttachment(noteId, blob, item.type);
      renderAttachments();
      showToast(`Slika dodana (${formatSize(blob.size)})`);
      return;
    }
  }
  // No image: default browser behavior (paste as text).
});
```

### Linux screenshot behavior

OS screenshot tools (gnome-screenshot, flameshot, KDE Spectacle, Shift+PrintScreen with "Copy to clipboard") write `image/png` to the clipboard. The handler above receives that as a `Blob` via `clipboardData.items` — no special-casing required.

### Filename generation

Browser does not provide a meaningful filename for clipboard images (`File.name` is typically `"image.png"` or empty). Generate:

```
screenshot-{YYYYMMDD-HHmmss}.png
```

Example: `screenshot-20260509-143022.png`. Sortable, human-readable.

### Toast feedback

After a successful image paste, a 2-second toast in the upper-right corner: *"Slika dodana (142 KB)"*. Without this, the user has no immediate confirmation since the attachment list is below the fold.

### Edge cases

| Situation | Behavior |
|---|---|
| Clipboard contains both text and image | Image wins (text paste is the default browser behavior elsewhere) |
| Image larger than 50 MB | Rejected; toast: *"Slika je prevelika (max 50 MB)"* |
| Unsupported format (BMP, TIFF) | Stored as-is; if render fails, placeholder ⚠ is shown |
| Paste outside the editor | Default browser behavior (no-op) |
| Drag-and-drop | Not supported in MVP |

## Error Handling

Strategy: **fail loud, never silent**. User-visible errors appear as non-blocking toasts in Croatian. All errors also `console.error` with `[notes]` prefix for DevTools inspection.

| Error | Trigger | UX |
|---|---|---|
| `db.open()` fails | Corruption, blocked by another connection | Full-screen message: *"Ne mogu otvoriti pohranu. [Pokušaj ponovno]"* |
| `QuotaExceededError` | Disk full / per-origin quota hit | Toast: *"Nema dovoljno prostora. Obriši stare bilješke ili privitke."* + transaction rollback |
| Attachment fails to render | Corrupted Blob, unsupported format | Inline placeholder ⚠; ✕ button still works to remove it |
| Concurrent popup edits | Two popup instances open the same note | Last-write-wins; per-field saves keep damage minimal. No optimistic locking in MVP. |

## Testing

| Layer | Type | Tooling | Coverage |
|---|---|---|---|
| `lib/db.js` | Unit | Jest + `fake-indexeddb` | open, get, put, delete, list, transactions |
| `lib/notes.js` | Unit | Jest + mock DB | createNote, updateNote, deleteNote (cascade), addAttachment, listNotes, search |
| `lib/clipboard.js` | Unit | Jest with synthesized paste events | image-vs-text branching, filename generation |
| Popup UI | Manual smoke test | Firefox `about:debugging` | See checklist below |

E2E with Selenium/Playwright is **out of scope** — overhead exceeds the value at this size.

### Manual smoke test checklist

Run before any local "release":

1. Open popup → empty list visible.
2. Create a note (title + body) → close popup → reopen → note persists.
3. OS screenshot (gnome-screenshot/flameshot/PrtSc) → Ctrl+V into editor body → image attached, toast confirms.
4. Reload Firefox → reopen popup → attachment renders correctly.
5. Delete a note → verify in DevTools → Storage → IndexedDB that its `attachments` records are gone (no orphans).
6. Type into search → list filters in real time.
7. Create > 100 notes via DevTools script → popup opens in < 500 ms.

### Tooling

- `package.json` with dev dependencies: `jest`, `fake-indexeddb`
- `npm test` runs the unit suite
- No CI; local development only

## Distribution

- **Development**: `about:debugging` → "Load Temporary Add-on" → select `manifest.json`. Re-loaded on each Firefox restart.
- **Permanent install**: zip and submit to [addons.mozilla.org](https://addons.mozilla.org) for free signing. Out of MVP scope.

## Open Questions

None at design freeze. Future work (post-MVP) likely includes: export/import, sync, tags, drag-and-drop. Each will get its own spec.
