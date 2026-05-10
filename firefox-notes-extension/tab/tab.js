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
  lastSavedAt: 0,
  currentMatchIndex: -1
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
    // Reset match cursor on each render
    state.currentMatchIndex = -1;
    // If there are matches, focus the first
    const marks = pre.querySelectorAll('mark');
    if (marks.length > 0) stepMatch(+1);
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

function stepMatch(delta) {
  const marks = document.querySelectorAll('#doc .body-pre mark');
  if (marks.length === 0) return;
  // Clear previous
  marks.forEach(m => m.classList.remove('current'));
  let idx = state.currentMatchIndex + delta;
  if (idx >= marks.length) idx = 0;
  if (idx < 0) idx = marks.length - 1;
  state.currentMatchIndex = idx;
  const m = marks[idx];
  m.classList.add('current');
  m.scrollIntoView({ block: 'center', behavior: 'smooth' });
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

async function renderRight() {
  const grid = $('#att-grid');
  const details = $('#details');
  const tagsBox = $('#tags');
  const rightCount = $('#right-att-count');

  grid.innerHTML = '';
  details.innerHTML = '';
  tagsBox.innerHTML = '';
  rightCount.textContent = '';

  if (!state.activeNoteId) return;

  const note = await getNote(state.db, state.activeNoteId);
  if (!note) return;

  // Attachments grid
  rightCount.textContent = `${note.attachmentIds.length}`;
  releaseRightObjectUrls();
  for (const aid of note.attachmentIds) {
    const a = await getAttachment(state.db, aid);
    grid.appendChild(buildAttachmentCard(aid, a));
  }
  // Always last: + Zalijepi add card
  const addCard = document.createElement('div');
  addCard.className = 'att-card add';
  addCard.innerHTML = `<span class="muted mono">+ Zalijepi</span>`;
  addCard.addEventListener('click', () => triggerFilePicker());
  grid.appendChild(addCard);

  injectIcons(grid);

  // Details
  const idShort = `${note.id.slice(0, 4)}…${note.id.slice(-4)}`;
  const totalSize = (note.body || '').length;
  details.innerHTML = `
    <div><dt class="muted">ID</dt><dd class="mono">${escapeHtml(idShort)}</dd></div>
    <div><dt class="muted">Stvoreno</dt><dd class="mono">${escapeHtml(formatDateTime(note.createdAt))}</dd></div>
    <div><dt class="muted">Uređeno</dt><dd class="mono">${escapeHtml(formatDateTime(note.updatedAt))}</dd></div>
    <div><dt class="muted">Veličina</dt><dd class="mono">${formatBytes(totalSize)}</dd></div>
    <div><dt class="muted">Verzija</dt><dd class="mono">1</dd></div>
  `;

  // Tags
  for (const t of (note.tags || [])) {
    const pill = document.createElement('span');
    pill.className = 't mono';
    pill.textContent = t;
    pill.title = 'Klikni za uklanjanje';
    pill.style.cursor = 'pointer';
    pill.addEventListener('click', async () => {
      const newTags = (note.tags || []).filter(x => x !== t);
      await setTags(state.db, note.id, newTags);
      await refreshNotes();
      renderRight();
      renderSidebar();
    });
    tagsBox.appendChild(pill);
  }
  const addTag = document.createElement('button');
  addTag.className = 't mono add-tag';
  addTag.type = 'button';
  addTag.textContent = '+ oznaka';
  addTag.addEventListener('click', async () => {
    const v = prompt('Nova oznaka:');
    if (!v) return;
    const newTags = Array.from(new Set([...(note.tags || []), v.trim()].filter(Boolean)));
    await setTags(state.db, note.id, newTags);
    await refreshNotes();
    renderRight();
    renderSidebar();
  });
  tagsBox.appendChild(addTag);
}

function buildAttachmentCard(aid, a) {
  const card = document.createElement('div');
  card.className = 'att-card';
  if (!a) {
    card.innerHTML = `<div class="frame"><span class="muted">⚠</span></div><div class="info mono"><span class="name">privitak nedostaje</span></div>`;
    return card;
  }
  const frame = document.createElement('div');
  frame.className = 'frame';
  if (a.mimeType && a.mimeType.startsWith('image/')) {
    const blob = a.thumbBlob instanceof Blob ? a.thumbBlob : a.blob;
    const url = URL.createObjectURL(blob);
    objectUrls.set(`right-${aid}`, url);
    const img = document.createElement('img');
    img.src = url;
    img.alt = '';
    img.style.cursor = 'zoom-in';
    img.addEventListener('click', () => openImageModal(a));
    frame.appendChild(img);
  } else {
    frame.innerHTML = `<span data-icon="image"></span>`;
  }
  card.appendChild(frame);

  const info = document.createElement('div');
  info.className = 'info mono';
  info.innerHTML = `<span class="name">${escapeHtml(a.filename)}</span><span class="size muted">${formatBytes(a.size)}</span>`;
  card.appendChild(info);
  return card;
}

function releaseRightObjectUrls() {
  for (const [k, url] of objectUrls.entries()) {
    if (k.startsWith('right-')) { URL.revokeObjectURL(url); objectUrls.delete(k); }
  }
}

function openImageModal(a) {
  const url = URL.createObjectURL(a.blob);
  $('#modal-img-el').src = url;
  $('#modal-img').classList.remove('hidden');
}

const SHORTCUTS = [
  { group: 'Globalno', items: [
    { keys: ['⌘', 'N'],     label: 'Nova bilješka' },
    { keys: ['⌘', 'O'],     label: 'Otvori karticu' },
    { keys: ['⌘', 'K'],     label: 'Fokusiraj pretragu' },
    { keys: ['⌘', '⇧', 'B'], label: 'Otvori popup' }
  ]},
  { group: 'Lista', items: [
    { keys: ['↓'],     label: 'Sljedeća bilješka' },
    { keys: ['↑'],     label: 'Prethodna bilješka' },
    { keys: ['↵'],     label: 'Otvori odabranu' },
    { keys: ['⌘', '⌫'], label: 'Obriši odabranu' },
    { keys: ['P'],     label: 'Pin / unpin' }
  ]},
  { group: 'Editor', items: [
    { keys: ['⌘', 'S'], label: 'Spremi (flush autosave)' },
    { keys: ['Esc'],    label: 'Natrag na listu' },
    { keys: ['⌘', 'V'], label: 'Zalijepi (slika ili tekst)' },
    { keys: ['↑', '↓'], label: 'Sljedeći / prethodni rezultat (kad je pretraga aktivna)' },
    { keys: ['⌘', '?'], label: 'Prikaz prečaca' }
  ]}
];

function openShortcutsModal() {
  const modal = $('#modal-shortcuts');
  modal.classList.remove('hidden');
  modal.innerHTML = `
    <div class="mc">
      <header class="mh">
        <h2 id="modal-shortcuts-title">Tipkovni prečaci</h2>
        <button class="ax" type="button" data-icon="x" aria-label="Zatvori"></button>
      </header>
      <div class="mb">
        ${SHORTCUTS.map(g => `
          <section class="kbd-section">
            <h3 class="section-label mono">${escapeHtml(g.group)}</h3>
            <div class="kbd-rows">
              ${g.items.map(it => `
                <div class="kbd-row">
                  <span class="kbd-label">${escapeHtml(it.label)}</span>
                  <span class="kbd-keys">${it.keys.map(k => `<kbd class="k">${escapeHtml(k)}</kbd>`).join('')}</span>
                </div>
              `).join('')}
            </div>
          </section>
        `).join('')}
      </div>
    </div>
  `;
  injectIcons(modal);
  modal.querySelector('.ax').addEventListener('click', closeShortcutsModal);
  modal.addEventListener('click', (e) => { if (e.target === modal) closeShortcutsModal(); });
}

function closeShortcutsModal() {
  $('#modal-shortcuts').classList.add('hidden');
  $('#modal-shortcuts').innerHTML = '';
}

function formatDateTime(t) {
  const d = new Date(t);
  return d.toLocaleString('hr-HR', { dateStyle: 'short', timeStyle: 'short' });
}

function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function triggerFilePicker() {
  // Lazy create a hidden input each time (no markup change required)
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = 'image/*,application/pdf';
  inp.multiple = true;
  inp.addEventListener('change', async () => {
    if (!state.activeNoteId) return;
    for (const f of inp.files) {
      try { await addAttachment(state.db, state.activeNoteId, f, f.type, f.name); }
      catch (err) { console.error('[notes] add file', err); }
    }
    await refreshNotes();
    await renderEditor();
    await renderRight();
    renderSidebar();
  });
  inp.click();
}

let toastTimer = null;
function showToast(message, kind = 'info') {
  const el = $('#toast');
  if (!el) return;
  el.textContent = message;
  el.classList.remove('hidden', 'error');
  if (kind === 'error') el.classList.add('error');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add('hidden'), 2000);
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
    if (ctrl && (k === '?' || k === '/')) {
      e.preventDefault();
      openShortcutsModal();
      return;
    }
    if (state.searchInDoc && (k === 'ArrowDown' || k === 'ArrowUp')) {
      e.preventDefault();
      stepMatch(k === 'ArrowDown' ? +1 : -1);
      return;
    }
    if (k === 'Escape') {
      // Close any open modal
      for (const m of document.querySelectorAll('.modal:not(.hidden)')) {
        m.classList.add('hidden');
        if (m.id !== 'modal-img') m.innerHTML = '';
      }
    }
  });

  $('#act-pin').addEventListener('click', async () => {
    if (!state.activeNoteId) return;
    await togglePin(state.db, state.activeNoteId);
    await refreshNotes();
    renderRight();
    renderSidebar();
  });

  $('#toggle-pin').addEventListener('click', () => $('#act-pin').click());

  $('#act-delete').addEventListener('click', async () => {
    if (!state.activeNoteId) return;
    if (!confirm('Obrisati ovu bilješku i sve privitke?')) return;
    await deleteNote(state.db, state.activeNoteId);
    state.activeNoteId = null;
    await refreshNotes();
    renderEditor();
    renderRight();
    renderSidebar();
  });

  $('#act-export').addEventListener('click', () => {
    // Phase G2 wires the modal; for now show a placeholder toast
    showToast('Izvoz dolazi u Phase G');
  });

  $('#modal-img').addEventListener('click', (e) => {
    if (e.target.id === 'modal-img') {
      $('#modal-img').classList.add('hidden');
      $('#modal-img-el').src = '';
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
