import { groupNotesByDate } from '../lib/grouping.js';

const day = 24 * 60 * 60 * 1000;

describe('groupNotesByDate', () => {
  // Use a fixed midday timestamp so day-boundary math is unambiguous in any tz.
  const now = new Date('2026-05-10T12:00:00').getTime();

  test('pinned go to Pribadane regardless of age', () => {
    const notes = [
      { id: 'a', updatedAt: now - 365 * day, pinned: true },
      { id: 'b', updatedAt: now - 1 * day,    pinned: false }
    ];
    const groups = groupNotesByDate(notes, now);
    expect(groups[0].label).toBe('Pribadane');
    expect(groups[0].notes.map(n => n.id)).toEqual(['a']);
  });

  test('group order is Pribadane, Danas, Jučer, Ovaj tjedan, Stariji', () => {
    const notes = [
      { id: 'p',  updatedAt: now,             pinned: true  },
      { id: 't1', updatedAt: now - 60_000,    pinned: false },
      { id: 'y',  updatedAt: now - 1 * day,   pinned: false },
      { id: 'w',  updatedAt: now - 4 * day,   pinned: false },
      { id: 'o',  updatedAt: now - 30 * day,  pinned: false }
    ];
    const labels = groupNotesByDate(notes, now).map(g => g.label);
    expect(labels).toEqual(['Pribadane', 'Danas', 'Jučer', 'Ovaj tjedan', 'Stariji']);
  });

  test('Danas excludes notes older than today midnight', () => {
    // Two days ago at the same hour should NOT be in Danas.
    const notes = [
      { id: 'now',     updatedAt: now,                pinned: false },
      { id: 'two-day', updatedAt: now - 2 * day,      pinned: false }
    ];
    const groups = groupNotesByDate(notes, now);
    const danas = groups.find(g => g.label === 'Danas');
    expect(danas.notes.map(n => n.id)).toEqual(['now']);
  });

  test('each group sorted by updatedAt DESC', () => {
    const notes = [
      { id: 'old',  updatedAt: now - 60_000, pinned: false },
      { id: 'new',  updatedAt: now,          pinned: false },
      { id: 'mid',  updatedAt: now - 30_000, pinned: false }
    ];
    const danas = groupNotesByDate(notes, now).find(g => g.label === 'Danas');
    expect(danas.notes.map(n => n.id)).toEqual(['new', 'mid', 'old']);
  });

  test('empty groups omitted', () => {
    const notes = [{ id: 'x', updatedAt: now, pinned: false }];
    expect(groupNotesByDate(notes, now).map(g => g.label)).toEqual(['Danas']);
  });

  test('empty input returns empty array', () => {
    expect(groupNotesByDate([], now)).toEqual([]);
  });

  test('treats missing pinned as false', () => {
    const notes = [{ id: 'x', updatedAt: now }]; // no pinned field
    const groups = groupNotesByDate(notes, now);
    expect(groups[0].label).toBe('Danas');
  });
});
