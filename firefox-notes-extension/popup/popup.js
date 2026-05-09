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
