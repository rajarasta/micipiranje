import { openDb } from '../lib/db.js';
import { createNote, listNotes, getNote, searchNotes, updateNote, deleteNote, addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { parsePaste } from '../lib/clipboard.js';
import { groupNotesByDate } from '../lib/grouping.js';
import { iconHtml } from './icons.js';

const $ = (sel) => document.querySelector(sel);

function injectIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]')) {
    const name = el.dataset.icon;
    if (name) el.innerHTML = iconHtml(name);
  }
}

const state = {
  db: null,
  currentNoteId: null,
  searchQuery: '',
  view: 'launcher',
  saveState: 'idle',     // 'idle' | 'saving' | 'saved' | 'error'
  lastSavedAt: 0
};

let bodyDebounceTimer = null;
const BODY_DEBOUNCE_MS = 500;
let saveStateInterval = null;

function renderSaveState() {
  const el = $('#save-state');
  if (!el) return;
  el.classList.remove('error', 'pulse');
  if (state.saveState === 'saving') {
    el.innerHTML = `<span class="label mono"><em>Sprema se…</em></span>`;
  } else if (state.saveState === 'error') {
    el.innerHTML = `<span class="dot error"></span><span class="label">Greška spremanja</span>`;
    el.classList.add('error');
  } else if (state.saveState === 'saved' && state.lastSavedAt) {
    const ageMs = Date.now() - state.lastSavedAt;
    el.innerHTML = `<span class="dot"></span><span class="label">Spremljeno · ${formatAge(ageMs)}</span>`;
  } else {
    el.innerHTML = `<span class="dot"></span><span class="label">Spremljeno</span>`;
  }
}

function startSaveStateTicker() {
  stopSaveStateTicker();
  saveStateInterval = setInterval(() => {
    if (state.view === 'editor') renderSaveState();
  }, 30_000);
}

function stopSaveStateTicker() {
  if (saveStateInterval) {
    clearInterval(saveStateInterval);
    saveStateInterval = null;
  }
}

function pulseSaved() {
  state.saveState = 'saved';
  state.lastSavedAt = Date.now();
  renderSaveState();
  const el = $('#save-state');
  if (el) {
    el.classList.add('pulse');
    setTimeout(() => el.classList.remove('pulse'), 1200);
  }
}

function setView(name) {
  state.view = name;
  $('#view-launcher').classList.toggle('hidden', name !== 'launcher');
  $('#view-list').classList.toggle('hidden', name !== 'list');
  $('#view-editor').classList.toggle('hidden', name !== 'editor');
}

function notePreview(note) {
  return (note.body || '').slice(0, 80);
}

function formatAge(ms) {
  if (ms < 60_000) return 'sad';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  if (ms < 7 * 86_400_000) return `${Math.floor(ms / 86_400_000)}d`;
  if (ms < 30 * 86_400_000) return `${Math.floor(ms / (7 * 86_400_000))}tj`;
  return `${Math.floor(ms / (30 * 86_400_000))}mj`;
}

async function init() {
  state.db = await openDb();
  injectIcons();
  bindStaticEvents();
  bindPasteHandler();
  bindAttachAddHandler();
  await renderLauncher();
  setView('launcher');
}

async function handleNewNote() {
  const note = await createNote(state.db);
  await openEditorFromId(note.id);
}

function bindStaticEvents() {
  $('#btn-new').addEventListener('click', () => handleNewNote().catch(err => console.error('[notes]', err)));
  $('#search').addEventListener('input', onSearchInput);
  $('#btn-back').addEventListener('click', () => { showList().catch(err => console.error('[notes]', err)); });
  $('#btn-delete').addEventListener('click', () => { onDeleteNoteClick().catch(err => console.error('[notes]', err)); });

  $('#hero-new').addEventListener('click', () => handleNewNote().catch(err => console.error('[notes] hero-new', err)));

  $('#hero-list').addEventListener('click', () => {
    setView('list');
    renderList().catch(err => console.error('[notes] renderList', err));
  });

  $('#hero-tab').addEventListener('click', async () => {
    try {
      const ext = (typeof browser !== 'undefined') ? browser : (typeof chrome !== 'undefined' ? chrome : null);
      if (!ext) { console.warn('[notes] no extension API'); return; }
      const url = ext.runtime.getURL('tab/tab.html');
      await ext.tabs.create({ url });
      window.close();
    } catch (err) { console.error('[notes] hero-tab', err); }
  });
}

function onSearchInput(e) {
  state.searchQuery = e.target.value;
  renderList();
}

async function renderLauncher() {
  const notes = await listNotes(state.db);
  $('#launcher-stats').textContent = notes.length === 0
    ? 'Još nema bilješki'
    : `${notes.length} ${notes.length === 1 ? 'bilješka' : (notes.length < 5 ? 'bilješke' : 'bilješki')}`;

  const recents = notes.slice(0, 4);
  const ul = $('#launcher-recents');
  ul.innerHTML = '';

  if (recents.length === 0) {
    const li = document.createElement('li');
    li.className = 'recent empty muted';
    li.textContent = 'Klikni "Nova bilješka" za prvi unos.';
    ul.appendChild(li);
    return;
  }

  for (const n of recents) {
    const li = document.createElement('li');
    li.className = 'recent';
    li.dataset.id = n.id;

    const preview = notePreview(n) || '(prazna bilješka)';
    const ageMs = Date.now() - n.updatedAt;

    li.innerHTML = `
      <span class="thumb" data-icon="${n.attachmentIds && n.attachmentIds.length ? 'image' : 'list'}"></span>
      <span class="preview">${escapeHtml(preview)}</span>
      <span class="age mono muted">${formatAge(ageMs)}</span>
    `;
    li.addEventListener('click', () => openEditorFromId(n.id));
    ul.appendChild(li);
  }
  injectIcons(ul);
}

async function renderList() {
  const allNotes = state.searchQuery
    ? await searchNotes(state.db, state.searchQuery)
    : await listNotes(state.db);

  const container = $('#note-list');
  container.innerHTML = '';

  // Update substats
  const sub = $('#list-substats');
  if (sub) {
    sub.textContent = allNotes.length === 0
      ? '— bilješki · auto-spremanje'
      : `${allNotes.length} ${pluralizeNotes(allNotes.length)} · auto-spremanje`;
  }

  if (allNotes.length === 0) {
    $('#empty-list').classList.remove('hidden');
    container.classList.add('hidden');
    return;
  }
  $('#empty-list').classList.add('hidden');
  container.classList.remove('hidden');

  // Release any thumbnail object URLs from previous render of list
  releaseListObjectUrls();

  const groups = groupNotesByDate(allNotes);
  for (const group of groups) {
    const head = document.createElement('div');
    head.className = 'group-head';
    head.innerHTML = `<span class="section-label mono">${escapeHtml(group.label)}</span><span class="mono muted">${group.notes.length}</span>`;
    container.appendChild(head);

    for (const note of group.notes) {
      container.appendChild(await buildNoteRow(note));
    }
  }
  injectIcons(container);
}

function pluralizeNotes(n) {
  if (n === 1) return 'bilješka';
  if (n < 5) return 'bilješke';
  return 'bilješki';
}

async function buildNoteRow(note) {
  const row = document.createElement('div');
  row.className = 'b-row';
  row.dataset.id = note.id;

  // Thumbnail cell
  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  const firstImg = await firstImageAttachment(note);
  if (firstImg && firstImg.thumbBlob instanceof Blob) {
    const url = URL.createObjectURL(firstImg.thumbBlob);
    objectUrls.set(`row-${note.id}`, url);
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    thumb.appendChild(img);
  } else if (note.attachmentIds && note.attachmentIds.length) {
    thumb.innerHTML = `<span data-icon="image"></span>`;
  } else {
    thumb.innerHTML = `<span data-icon="list"></span>`;
  }

  // Body cell
  const body = document.createElement('div');
  body.className = 'body';
  const preview = notePreview(note);
  const ageMs = Date.now() - note.updatedAt;
  body.innerHTML = `
    <div class="preview">${escapeHtml(preview) || '<em class="muted">(prazna bilješka)</em>'}</div>
    <div class="meta mono muted">
      ${formatAge(ageMs)} · ${note.body ? note.body.length : 0} zn.
    </div>
  `;

  // Right cell
  const right = document.createElement('div');
  right.className = 'right';
  const attCount = note.attachmentIds ? note.attachmentIds.length : 0;
  right.innerHTML = `
    <span class="age mono muted">${formatAge(ageMs)}</span>
    ${attCount ? `<span class="att-pill mono"><span data-icon="paperclip"></span> ${attCount}</span>` : ''}
  `;

  row.append(thumb, body, right);
  row.addEventListener('click', () => openEditorFromId(note.id));
  return row;
}

async function firstImageAttachment(note) {
  if (!note.attachmentIds || note.attachmentIds.length === 0) return null;
  for (const id of note.attachmentIds) {
    const a = await getAttachment(state.db, id);
    if (a && a.mimeType && a.mimeType.startsWith('image/')) return a;
  }
  return null;
}

function releaseListObjectUrls() {
  for (const [key, url] of objectUrls.entries()) {
    if (key.startsWith('row-')) {
      URL.revokeObjectURL(url);
      objectUrls.delete(key);
    }
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

async function openEditorFromId(id) {
  releaseListObjectUrls();
  await openEditor(id);
  setView('editor');
}

async function openEditor(id) {
  const note = await getNote(state.db, id);
  if (!note) {
    showList();
    return;
  }
  state.currentNoteId = id;
  $('#editor-body').value = note.body || '';
  setView('editor');
  renderAttachments(note);
  rebindEditorEvents();
  state.lastSavedAt = note.updatedAt;
  state.saveState = 'saved';
  renderSaveState();
  startSaveStateTicker();
  $('#editor-body').focus();
}

function rebindEditorEvents() {
  $('#editor-body').oninput = onBodyInput;
}

function unbindEditorEvents() {
  $('#editor-body').oninput = null;
  if (bodyDebounceTimer) {
    clearTimeout(bodyDebounceTimer);
    bodyDebounceTimer = null;
  }
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
  state.saveState = 'saving';
  renderSaveState();
  try {
    await updateNote(state.db, state.currentNoteId, { body: $('#editor-body').value });
    pulseSaved();
  } catch (err) {
    console.error('[notes] flushBody', err);
    state.saveState = 'error';
    renderSaveState();
  }
}

async function flushAndPrune() {
  if (!state.currentNoteId) return;
  await flushBody();

  const note = await getNote(state.db, state.currentNoteId);
  if (note && !note.body.trim() && note.attachmentIds.length === 0) {
    await deleteNote(state.db, state.currentNoteId);
  }
}

const objectUrls = new Map();  // attachmentId -> objectUrl, for cleanup

function renderAttachments(note) {
  const ul = $('#attachment-list');
  ul.innerHTML = '';
  for (const attId of note.attachmentIds) {
    const placeholder = document.createElement('div');
    placeholder.className = 'att-chip';
    placeholder.dataset.id = attId;
    ul.appendChild(placeholder);
    renderAttachmentRow(attId, placeholder).catch(err => console.error('[notes] att render', err));
  }
  // Update count label
  const lbl = document.querySelector('.att-count-label');
  if (lbl) lbl.textContent = `PRIVITCI · ${note.attachmentIds.length}`;
}

async function renderAttachmentRow(attId, li) {
  // Release any existing object URL for this attachment so re-renders don't leak.
  releaseObjectUrl(attId);

  const att = await getAttachment(state.db, attId);

  if (!att) {
    li.className = 'att-chip missing';
    li.innerHTML = `<span class="swatch">⚠</span><span class="name mono">privitak nedostaje</span><button class="ax" type="button" data-icon="x" aria-label="Ukloni"></button>`;
    li.querySelector('button').addEventListener('click', () => removeAttachmentClick(attId));
    injectIcons(li);
    return;
  }

  li.className = 'att-chip';
  li.innerHTML = '';

  // Swatch: thumbnail image if available, original blob if image but no thumb, doc icon if non-image
  const swatch = document.createElement('span');
  swatch.className = 'swatch';
  if (att.mimeType && att.mimeType.startsWith('image/')) {
    const useBlob = att.thumbBlob instanceof Blob ? att.thumbBlob : att.blob;
    const url = URL.createObjectURL(useBlob);
    objectUrls.set(attId, url);
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.addEventListener('click', () => openModal(URL.createObjectURL(att.blob)));
    img.onerror = () => { swatch.replaceWith(document.createTextNode('⚠')); };
    swatch.appendChild(img);
  } else {
    // generic document badge
    swatch.innerHTML = `<span data-icon="image"></span>`;
  }

  // Filename
  const name = document.createElement('span');
  name.className = 'name mono';
  name.title = att.filename;
  name.textContent = att.filename;

  // Remove button
  const ax = document.createElement('button');
  ax.className = 'ax';
  ax.type = 'button';
  ax.setAttribute('aria-label', 'Ukloni');
  ax.dataset.icon = 'x';
  ax.addEventListener('click', () => removeAttachmentClick(attId));

  li.append(swatch, name, ax);
  injectIcons(li);
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

function bindPasteHandler() {
  $('#editor-body').addEventListener('paste', onPaste);
}

function bindAttachAddHandler() {
  const btn = $('#btn-add-att');
  const input = $('#file-input');
  if (!btn || !input) return;

  btn.addEventListener('click', () => input.click());
  input.addEventListener('change', async (e) => {
    if (!state.currentNoteId) return;
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    for (const f of files) {
      try {
        const att = await addAttachment(state.db, state.currentNoteId, f, f.type, f.name);
        showToast(`${f.name} dodano (${formatSize(att.size)})`);
      } catch (err) {
        console.error('[notes] file add', err);
        showToast('Greška pri dodavanju datoteke', 'error');
      }
    }
    const note = await getNote(state.db, state.currentNoteId);
    if (note) renderAttachments(note);
  });
}

async function onPaste(e) {
  const noteId = state.currentNoteId;
  if (!noteId) return;
  const result = parsePaste(e);
  if (!result) return;

  if (result.kind === 'rejected') {
    showToast(`Slika je prevelika (${formatSize(result.size)}, max 50 MB)`, 'error');
    return;
  }

  try {
    const att = await addAttachment(state.db, noteId, result.blob, result.mimeType, result.filename);
    showToast(`Slika dodana (${formatSize(att.size)})`);
    if (state.currentNoteId !== noteId) return;
    const note = await getNote(state.db, noteId);
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

async function onDeleteNoteClick() {
  if (!state.currentNoteId) return;
  if (!confirm('Obrisati ovu bilješku i sve privitke?')) return;
  unbindEditorEvents();
  stopSaveStateTicker();
  await deleteNote(state.db, state.currentNoteId);
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  setView('list');
  await renderList();
}

async function showList() {
  unbindEditorEvents();
  stopSaveStateTicker();
  await flushAndPrune();
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  setView('list');
  await renderList();
}

window.addEventListener('pagehide', () => {
  flushAndPrune().catch(err => console.error('[notes] flush on hide failed', err));
});

$('#modal').addEventListener('click', () => {
  $('#modal').classList.add('hidden');
  $('#modal-img').src = '';
});

init().catch(err => {
  console.error('[notes] init failed', err);
  // MV3 CSP forbids inline onclick — bind via addEventListener.
  $('#app').innerHTML = `<div class="empty">Ne mogu otvoriti pohranu. <button id="btn-retry" type="button">Pokušaj ponovno</button></div>`;
  $('#btn-retry').addEventListener('click', () => location.reload());
});
