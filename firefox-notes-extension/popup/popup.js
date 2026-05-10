import { openDb } from '../lib/db.js';
import { createNote, listNotes, getNote, searchNotes, updateNote, deleteNote, addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { parsePaste } from '../lib/clipboard.js';
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
  view: 'launcher'
};

let bodyDebounceTimer = null;
const BODY_DEBOUNCE_MS = 500;

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
  const notes = state.searchQuery
    ? await searchNotes(state.db, state.searchQuery)
    : await listNotes(state.db);

  const container = $('#note-list');
  container.innerHTML = '';

  if (notes.length === 0) {
    $('#empty-list').classList.remove('hidden');
    return;
  }
  $('#empty-list').classList.add('hidden');

  for (const note of notes) {
    const row = document.createElement('div');
    row.className = 'note-card';
    row.dataset.id = note.id;
    row.innerHTML = `
      <div class="title">
        <span>${escapeHtml(note.title) || '<em>(bez naslova)</em>'}</span>
        ${note.attachmentIds.length ? `<span class="att-count">🖼 ${note.attachmentIds.length}</span>` : ''}
      </div>
      <div class="preview">${escapeHtml(note.body.slice(0, 120)) || '<em>—</em>'}</div>
    `;
    row.addEventListener('click', () => openEditorFromId(note.id));
    container.appendChild(row);
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
  await updateNote(state.db, state.currentNoteId, { body: $('#editor-body').value });
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
    const placeholder = document.createElement('li');
    placeholder.className = 'att-item';
    placeholder.dataset.id = attId;
    ul.appendChild(placeholder);
    renderAttachmentRow(attId, placeholder).catch(err => console.error('[notes] att render', err));
  }
}

async function renderAttachmentRow(attId, li) {
  const att = await getAttachment(state.db, attId);

  if (!att) {
    li.innerHTML = `<span class="thumb">⚠</span><span class="name">privitak nedostaje</span><button type="button">✕</button>`;
    li.querySelector('button').addEventListener('click', () => removeAttachmentClick(attId));
    return;
  }

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
  await deleteNote(state.db, state.currentNoteId);
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  setView('list');
  await renderList();
}

async function showList() {
  unbindEditorEvents();
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
