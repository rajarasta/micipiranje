import { exportMarkdown, exportJson } from '../lib/export.js';

describe('exportMarkdown', () => {
  test('returns a Blob whose text contains a frontmatter block per note', async () => {
    const notes = [
      { id: 'n1', body: 'Hello world', createdAt: 1714000000000, updatedAt: 1714000050000, tags: ['posao'], attachmentIds: [] },
      { id: 'n2', body: 'Druga.', createdAt: 1714100000000, updatedAt: 1714100050000, tags: [], attachmentIds: ['a1'] }
    ];
    const blob = exportMarkdown(notes);
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('text/markdown');
    const text = await blob.text();
    expect(text).toMatch(/id: n1/);
    expect(text).toMatch(/id: n2/);
    expect(text).toMatch(/Hello world/);
    expect(text).toMatch(/Druga\./);
    expect(text).toMatch(/tags: \["posao"\]/);
    expect(text).toMatch(/tags: \[\]/);
    expect(text).toMatch(/attachments: \["a1"\]/);
    // ISO timestamps
    expect(text).toMatch(/createdAt: 2024-/);
  });

  test('handles empty list', async () => {
    const blob = exportMarkdown([]);
    const text = await blob.text();
    expect(text).toBe('');
  });
});

describe('exportJson', () => {
  test('serialises notes plus base64 attachments', async () => {
    const notes = [{ id: 'n1', body: 'hi', tags: [], attachmentIds: ['a1'], createdAt: 1, updatedAt: 1 }];
    const attBlob = new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' });
    const attsByNoteId = { n1: [{ id: 'a1', blob: attBlob, mimeType: 'image/jpeg', filename: 'photo.jpg', size: 3 }] };

    const blob = await exportJson(notes, attsByNoteId);
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('application/json');
    const obj = JSON.parse(await blob.text());
    expect(obj.notes.length).toBe(1);
    expect(obj.notes[0].id).toBe('n1');
    expect(obj.attachments.length).toBe(1);
    const a = obj.attachments[0];
    expect(a.id).toBe('a1');
    expect(a.noteId).toBe('n1');
    expect(a.mimeType).toBe('image/jpeg');
    expect(a.filename).toBe('photo.jpg');
    expect(a.size).toBe(3);
    expect(typeof a.dataBase64).toBe('string');
    expect(a.dataBase64.length).toBeGreaterThan(0);
    // base64 of 0xff 0xd8 0xff is /9j/
    expect(a.dataBase64).toMatch(/^\/9j\//);
  });

  test('handles notes with no attachments', async () => {
    const notes = [{ id: 'n1', body: 'hi', tags: [], attachmentIds: [], createdAt: 1, updatedAt: 1 }];
    const blob = await exportJson(notes, {});
    const obj = JSON.parse(await blob.text());
    expect(obj.notes.length).toBe(1);
    expect(obj.attachments).toEqual([]);
  });
});
