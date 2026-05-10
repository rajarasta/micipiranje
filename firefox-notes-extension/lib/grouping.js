function startOfDay(t) {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

const ORDER = ['Pribadane', 'Danas', 'Jučer', 'Ovaj tjedan', 'Stariji'];

export function groupNotesByDate(notes, now = Date.now()) {
  const dayMs = 24 * 60 * 60 * 1000;
  const todayStart = startOfDay(now);
  const yStart = todayStart - dayMs;
  const wStart = todayStart - 7 * dayMs;

  const buckets = {
    Pribadane: [],
    Danas: [],
    'Jučer': [],
    'Ovaj tjedan': [],
    Stariji: []
  };

  for (const n of notes) {
    if (n.pinned) { buckets.Pribadane.push(n); continue; }
    if (n.updatedAt >= todayStart) buckets.Danas.push(n);
    else if (n.updatedAt >= yStart) buckets['Jučer'].push(n);
    else if (n.updatedAt >= wStart) buckets['Ovaj tjedan'].push(n);
    else buckets.Stariji.push(n);
  }

  return ORDER
    .filter(k => buckets[k].length > 0)
    .map(k => ({
      label: k,
      notes: buckets[k].slice().sort((a, b) => b.updatedAt - a.updatedAt)
    }));
}
