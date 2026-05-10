export function derivedTagFilters(notes, top = 4) {
  const counts = new Map();
  for (const n of notes) {
    if (!Array.isArray(n.tags)) continue;
    for (const t of n.tags) {
      counts.set(t, (counts.get(t) || 0) + 1);
    }
  }
  const sorted = Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    return a[0].localeCompare(b[0]);
  });
  return ['Sve', ...sorted.slice(0, top).map(([t]) => t)];
}
