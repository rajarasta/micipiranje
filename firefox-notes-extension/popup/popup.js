import { openDb } from '../lib/db.js';
import { createNote, listNotes, getNote, searchNotes, updateNote, deleteNote, addAttachment, removeAttachment, getAttachment } from '../lib/notes.js';
import { parsePaste } from '../lib/clipboard.js';

const $ = (sel) => document.querySelector(sel);

const state = {
  db: null,
  currentNoteId: null,
  searchQuery: ''
};

let bodyDebounceTimer = null;
const BODY_DEBOUNCE_MS = 500;

async function init() {
  state.db = await openDb();
  bindStaticEvents();
  bindPasteHandler();
  await renderList();
}

function bindStaticEvents() {
  $('#btn-new').addEventListener('click', onNewNoteClick);
  $('#search').addEventListener('input', onSearchInput);
  $('#btn-back').addEventListener('click', () => { showList().catch(err => console.error('[notes]', err)); });
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
  renderAttachments(note);
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
  await updateNote(state.db, state.currentNoteId, { title: $('#editor-title').value });

  const note = await getNote(state.db, state.currentNoteId);
  if (note && !note.title.trim() && !note.body.trim() && note.attachmentIds.length === 0) {
    await deleteNote(state.db, state.currentNoteId);
  }
}

const objectUrls = new Map();  // attachmentId -> objectUrl, for cleanup

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

async function showList() {
  await flushAndPrune();
  for (const id of objectUrls.keys()) URL.revokeObjectURL(objectUrls.get(id));
  objectUrls.clear();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
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
