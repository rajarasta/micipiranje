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
