function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function splitMatches(text, query) {
  if (!text) return [];
  if (!query) return [{ text, hi: false }];
  const re = new RegExp(escapeRegex(query), 'gi');
  const out = [];
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) out.push({ text: text.slice(last, m.index), hi: false });
    out.push({ text: m[0], hi: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), hi: false });
  return out;
}
