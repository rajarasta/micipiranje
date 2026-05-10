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
  $('#side-count').textContent = state.notes.length === 0 ? '' : `${state.notes.length}`;
  renderFilters();
  renderSidebarList();
}

function renderFilters() {
  const tags = derivedTagFilters(state.notes, 4);
  const div = $('#side-filters');
  div.innerHTML = '';
  for (const t of tags) {
    const btn = document.createElement('button');
    btn.className = 'chip mono' + (state.filterTag === t ? ' active' : '');
    btn.type = 'button';
    btn.textContent = t === 'Sve' ? 'Sve' : t;
    btn.addEventListener('click', () => {
      state.filterTag = t;
      renderFilters();
      renderSidebarList();
    });
    div.appendChild(btn);
  }
}

function renderSidebarList() {
  const filtered = state.notes.filter(n => {
    if (state.filterTag !== 'Sve') {
      if (!n.tags || !n.tags.includes(state.filterTag)) return false;
    }
    if (state.search) {
      const q = state.search.toLowerCase();
      if (!n.body || !n.body.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const ul = $('#side-list');
  ul.innerHTML = '';

  if (filtered.length === 0) {
    const p = document.createElement('div');
    p.className = 'empty muted';
    p.style.padding = '12px 14px';
    p.textContent = state.search ? 'Nema rezultata.' : 'Nema bilješki.';
    ul.appendChild(p);
    return;
  }

  // Release previous row thumb URLs
  releaseRowObjectUrls();

  const groups = groupNotesByDate(filtered);
  for (const group of groups) {
    const h = document.createElement('div');
    h.className = 'group-head';
    h.innerHTML = `<span class="section-label mono">${escapeHtml(group.label)}</span><span class="mono muted">${group.notes.length}</span>`;
    ul.appendChild(h);
    for (const n of group.notes) {
      ul.appendChild(buildSidebarRow(n));
    }
  }
}

const objectUrls = new Map();

function releaseRowObjectUrls() {
  for (const [k, url] of objectUrls.entries()) {
    if (k.startsWith('row-')) { URL.revokeObjectURL(url); objectUrls.delete(k); }
  }
}

function buildSidebarRow(n) {
  const row = document.createElement('div');
  row.className = 'b-row' + (state.activeNoteId === n.id ? ' active' : '');
  row.dataset.id = n.id;

  const thumb = document.createElement('div');
  thumb.className = 'thumb';
  // For tab sidebar, defer thumbnail load (DB round-trip) — start with icon, async upgrade if image
  if (n.attachmentIds && n.attachmentIds.length) {
    thumb.innerHTML = `<span data-icon="image"></span>`;
    upgradeRowThumb(n, thumb).catch(() => {});
  } else {
    thumb.innerHTML = `<span data-icon="list"></span>`;
  }

  const body = document.createElement('div');
  body.className = 'body';
  const preview = (n.body || '').slice(0, 80);
  const ageMs = Date.now() - n.updatedAt;
  body.innerHTML = `
    <div class="preview">${escapeHtml(preview) || '<em class="muted">(prazna)</em>'}</div>
    <div class="meta mono muted">${formatAge(ageMs)} · ${n.body ? n.body.length : 0} zn.</div>
  `;

  const right = document.createElement('div');
  right.className = 'right';
  right.innerHTML = `
    <span class="age mono muted">${formatAge(ageMs)}</span>
    ${n.attachmentIds && n.attachmentIds.length ? `<span class="att-pill mono"><span data-icon="paperclip"></span> ${n.attachmentIds.length}</span>` : ''}
  `;

  row.append(thumb, body, right);
  row.addEventListener('click', () => openNote(n.id));

  injectIcons(row);
  return row;
}

async function upgradeRowThumb(n, thumbEl) {
  for (const id of n.attachmentIds || []) {
    const a = await getAttachment(state.db, id);
    if (a && a.mimeType && a.mimeType.startsWith('image/')) {
      const blob = a.thumbBlob instanceof Blob ? a.thumbBlob : a.blob;
      const url = URL.createObjectURL(blob);
      objectUrls.set(`row-${n.id}`, url);
      thumbEl.innerHTML = `<img src="${url}" alt="">`;
      return;
    }
  }
}

let bodyDebounceTimer = null;
const BODY_DEBOUNCE_MS = 500;

async function renderEditor() {
  const doc = $('#doc');
  const path = $('#crumb-path');

  if (!state.activeNoteId) {
    doc.innerHTML = '<div class="empty muted">Odaberi bilješku iz lijevog popisa.</div>';
    path.textContent = 'Bilješke';
    $('#foot-save').textContent = '';
    $('#foot-chars').textContent = '';
    $('#foot-atts').textContent = '';
    return;
  }

  const note = await getNote(state.db, state.activeNoteId);
  if (!note) {
    state.activeNoteId = null;
    return renderEditor();
  }

  // Crumbs
  const head = (note.body || '').slice(0, 32);
  path.innerHTML = `Bilješke <span class="sep-slash"> / </span> <strong class="ink">${escapeHtml(head)}${note.body && note.body.length > 32 ? '…' : ''}</strong>`;

  // Body
  doc.innerHTML = '';

  // Meta line
  const meta = document.createElement('div');
  meta.className = 'meta-line mono muted';
  const paragraphs = (note.body || '').split(/\n{2,}/).filter(Boolean).length;
  const tagPills = (note.tags || []).map(t => `<span class="t mono">${escapeHtml(t)}</span>`).join(' ');
  meta.innerHTML = `Uređeno ${formatAge(Date.now() - note.updatedAt)} ${tagPills} · ${(note.body || '').length} znakova · ${paragraphs} odlomaka`;
  doc.appendChild(meta);

  if (state.searchInDoc && state.search) {
    const pre = document.createElement('pre');
    pre.className = 'body-pre';
    const runs = splitMatches(note.body || '', state.search);
    pre.innerHTML = runs.map(r => r.hi
      ? `<mark>${escapeHtml(r.text)}</mark>`
      : escapeHtml(r.text)
    ).join('');
    doc.appendChild(pre);
  } else {
    const ta = document.createElement('textarea');
    ta.id = 'body-textarea';
    ta.className = 'body-textarea';
    ta.value = note.body || '';
    ta.placeholder = 'Bilješka…';
    ta.addEventListener('input', onBodyInput);
    doc.appendChild(ta);
  }

  // Footer
  state.lastSavedAt = note.updatedAt;
  state.saveState = 'saved';
  renderFootSave();
  $('#foot-chars').textContent = `${(note.body || '').length} zn.`;
  $('#foot-atts').textContent = `${note.attachmentIds.length} privitka${note.attachmentIds.length === 1 ? '' : ''}`;
}

function renderFootSave() {
  const el = $('#foot-save');
  if (!el) return;
  if (state.saveState === 'saving') {
    el.textContent = 'Sprema se…';
  } else if (state.saveState === 'error') {
    el.textContent = 'Greška spremanja';
  } else if (state.lastSavedAt) {
    el.textContent = `Spremljeno · ${formatAge(Date.now() - state.lastSavedAt)}`;
  } else {
    el.textContent = '';
  }
}

function onBodyInput() {
  if (bodyDebounceTimer) clearTimeout(bodyDebounceTimer);
  bodyDebounceTimer = setTimeout(flushBody, BODY_DEBOUNCE_MS);
}

async function flushBody() {
  if (bodyDebounceTimer) { clearTimeout(bodyDebounceTimer); bodyDebounceTimer = null; }
  if (!state.activeNoteId) return;
  const ta = $('#body-textarea');
  if (!ta) return;
  state.saveState = 'saving';
  renderFootSave();
  try {
    const updated = await updateNote(state.db, state.activeNoteId, { body: ta.value });
    state.saveState = 'saved';
    state.lastSavedAt = updated.updatedAt;
    renderFootSave();
    // Update sidebar preview without full re-fetch:
    const idx = state.notes.findIndex(n => n.id === state.activeNoteId);
    if (idx >= 0) {
      state.notes[idx] = { ...state.notes[idx], ...updated };
      renderSidebarList();
    }
  } catch (err) {
    console.error('[notes] flushBody', err);
    state.saveState = 'error';
    renderFootSave();
  }
}

window.addEventListener('pagehide', () => {
  flushBody().catch(() => {});
});

function renderRight() {
  // Implemented in Task E4.
  $('#att-grid').innerHTML = '';
  $('#details').innerHTML = '';
  $('#tags').innerHTML = '';
}

function bindEvents() {
  $('#side-new').addEventListener('click', () => createAndOpen().catch(err => console.error('[notes]', err)));
  $('#side-search').addEventListener('input', (e) => {
    state.search = e.target.value;
    renderSidebar();
  });

  $('#toggle-search').addEventListener('click', () => {
    state.searchInDoc = !state.searchInDoc;
    $('#toggle-search').classList.toggle('active', state.searchInDoc);
    renderEditor();
  });

  document.addEventListener('keydown', (e) => {
    const k = e.key;
    const ctrl = e.metaKey || e.ctrlKey;
    if (ctrl && k.toLowerCase() === 'k') { e.preventDefault(); $('#side-search').focus(); return; }
    if (ctrl && k.toLowerCase() === 'n' && !isTypingInTextarea(e.target)) { e.preventDefault(); createAndOpen(); return; }
    if (k === 'Escape') {
      // Close any open modal
      for (const m of document.querySelectorAll('.modal:not(.hidden)')) m.classList.add('hidden');
    }
  });
}

function isTypingInTextarea(target) {
  return target && (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT');
}

async function createAndOpen() {
  const note = await createNote(state.db);
  await refreshNotes();
  await openNote(note.id);
  renderSidebar();
}

async function openNote(id) {
  state.activeNoteId = id;
  renderEditor();
  renderRight();
  // Update active class on sidebar rows
  for (const row of document.querySelectorAll('#side-list .b-row')) {
    row.classList.toggle('active', row.dataset.id === id);
  }
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
