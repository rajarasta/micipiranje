import { openDb } from '../lib/db.js';
import {
  listNotes, getNote, createNote, updateNote, deleteNote,
  togglePin, setTags, addAttachment, removeAttachment, getAttachment
} from '../lib/notes.js';
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
  notes: [],
  saveState: 'idle',
  lastSavedAt: 0
};

function injectIcons(root = document) {
  for (const el of root.querySelectorAll('[data-icon]')) {
    const name = el.dataset.icon;
    if (name) el.innerHTML = iconHtml(name);
  }
}

function escapeHtml(str) {
  return String(str || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function formatAge(ms) {
  if (ms < 60_000) return 'sad';
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m`;
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h`;
  if (ms < 7 * 86_400_000) return `${Math.floor(ms / 86_400_000)}d`;
  if (ms < 30 * 86_400_000) return `${Math.floor(ms / (7 * 86_400_000))}tj`;
  return `${Math.floor(ms / (30 * 86_400_000))}mj`;
}

async function refreshNotes() {
  state.notes = await listNotes(state.db);
}

function renderSidebar() {
  // Implemented in Task E2.
  $('#side-count').textContent = state.notes.length === 0 ? '' : `${state.notes.length}`;
  // For now, render empty containers so the layout renders without errors.
  $('#side-filters').innerHTML = '';
  $('#side-list').innerHTML = '';
}

function renderEditor() {
  // Implemented in Task E3.
  if (!state.activeNoteId) return;
}

function renderRight() {
  // Implemented in Task E4.
  $('#att-grid').innerHTML = '';
  $('#details').innerHTML = '';
  $('#tags').innerHTML = '';
}

function bindEvents() {
  // Implemented in Task E2.
}

async function init() {
  state.db = await openDb();
  injectIcons();
  await refreshNotes();
  renderSidebar();
  renderEditor();
  renderRight();
  bindEvents();
}

init().catch(err => {
  console.error('[notes] tab init', err);
  document.body.innerHTML = `<div style="padding:24px;font-family:system-ui">Ne mogu otvoriti pohranu.<br><br><button onclick="location.reload()">Pokušaj ponovno</button></div>`;
});
