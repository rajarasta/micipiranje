export const MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024;

const EXT_BY_MIME = {
  'image/png': 'png',
  'image/jpeg': 'jpg',
  'image/gif': 'gif',
  'image/webp': 'webp',
  'image/bmp': 'bmp'
};

function pad(n, width = 2) {
  return String(n).padStart(width, '0');
}

export function screenshotFilename(mimeType, date = new Date()) {
  const ext = EXT_BY_MIME[mimeType] || 'bin';
  const ts = `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}-${pad(date.getHours())}${pad(date.getMinutes())}${pad(date.getSeconds())}`;
  return `screenshot-${ts}.${ext}`;
}

export function parsePaste(event) {
  const items = event.clipboardData?.items ?? [];
  for (const item of items) {
    if (!item.type || !item.type.startsWith('image/')) continue;
    const blob = item.getAsFile();
    if (!blob) continue;
    event.preventDefault();
    if (blob.size > MAX_ATTACHMENT_BYTES) {
      return { kind: 'rejected', reason: 'too-large', size: blob.size };
    }
    return {
      kind: 'image',
      blob,
      mimeType: item.type,
      filename: screenshotFilename(item.type)
    };
  }
  return null;
}
