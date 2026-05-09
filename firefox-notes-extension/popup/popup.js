import { openDb } from '../lib/db.js';
import { createNote, listNotes, getNote, searchNotes, updateNote, deleteNote } from '../lib/notes.js';

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

function renderAttachments(note) {
  $('#attachment-list').innerHTML = '';
}

async function showList() {
  await flushAndPrune();
  state.currentNoteId = null;
  $('#view-editor').classList.add('hidden');
  $('#view-list').classList.remove('hidden');
  await renderList();
}

window.addEventListener('pagehide', () => {
  flushAndPrune().catch(err => console.error('[notes] flush on hide failed', err));
});

init().catch(err => {
  console.error('[notes] init failed', err);
  // MV3 CSP forbids inline onclick — bind via addEventListener.
  $('#app').innerHTML = `<div class="empty">Ne mogu otvoriti pohranu. <button id="btn-retry" type="button">Pokušaj ponovno</button></div>`;
  $('#btn-retry').addEventListener('click', () => location.reload());
});
