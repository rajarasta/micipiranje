function frontmatter(note) {
  const tags = (note.tags || []).map(t => `"${t}"`).join(', ');
  const atts = (note.attachmentIds || []).map(a => `"${a}"`).join(', ');
  return [
    '---',
    `id: ${note.id}`,
    `createdAt: ${new Date(note.createdAt).toISOString()}`,
    `updatedAt: ${new Date(note.updatedAt).toISOString()}`,
    `tags: [${tags}]`,
    `attachments: [${atts}]`,
    '---',
    ''
  ].join('\n');
}

export function exportMarkdown(notes) {
  if (!notes || notes.length === 0) return new Blob([''], { type: 'text/markdown' });
  const text = notes.map(n => frontmatter(n) + (n.body || '') + '\n').join('\n\n---\n\n');
  return new Blob([text], { type: 'text/markdown' });
}

export async function exportJson(notes, attachmentsByNoteId) {
  const flatAtts = [];
  for (const [noteId, atts] of Object.entries(attachmentsByNoteId || {})) {
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
      const dataUrl = String(fr.result || '');
      const idx = dataUrl.indexOf(',');
      resolve(idx >= 0 ? dataUrl.slice(idx + 1) : '');
    };
    fr.onerror = () => reject(fr.error);
    fr.readAsDataURL(blob);
  });
}

let _jsZipPromise = null;

async function loadJSZip() {
  if (typeof globalThis.JSZip === 'function') return globalThis.JSZip;
  if (_jsZipPromise) return _jsZipPromise;
  _jsZipPromise = new Promise((resolve, reject) => {
    // Resolve the path via the WebExtension API if available; fall back to relative
    const ext = (typeof browser !== 'undefined') ? browser : (typeof chrome !== 'undefined' ? chrome : null);
    const url = ext && ext.runtime && ext.runtime.getURL
      ? ext.runtime.getURL('lib/vendor/jszip.min.js')
      : '../lib/vendor/jszip.min.js';
    const s = document.createElement('script');
    s.src = url;
    s.onload = () => {
      if (typeof globalThis.JSZip === 'function') resolve(globalThis.JSZip);
      else reject(new Error('JSZip loaded but global not exposed'));
    };
    s.onerror = () => reject(new Error('Failed to load JSZip vendor bundle'));
    document.head.appendChild(s);
  });
  return _jsZipPromise;
}

export async function exportZip(notes, attachmentsByNoteId) {
  const JSZip = await loadJSZip();
  const zip = new JSZip();

  // One markdown file per note
  for (const note of notes) {
    const md = noteToMarkdown(note);
    const slug = (note.id || 'note').slice(0, 8);
    zip.file(`notes/${slug}.md`, md);
  }

  // Attachments under attachments/{noteId}/{filename}
  for (const [noteId, atts] of Object.entries(attachmentsByNoteId || {})) {
    for (const a of atts) {
      const safeName = (a.filename || a.id).replace(/[\/\\:*?"<>|]/g, '_');
      zip.file(`attachments/${noteId}/${safeName}`, a.blob);
    }
  }

  return await zip.generateAsync({ type: 'blob', mimeType: 'application/zip' });
}

function noteToMarkdown(note) {
  return frontmatter(note) + (note.body || '') + '\n';
}
