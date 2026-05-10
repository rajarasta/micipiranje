export async function generateThumbnail(blob, size = 72) {
  if (!blob || typeof blob !== 'object' || !('type' in blob) || !blob.type.startsWith('image/')) {
    throw new Error('Cannot thumbnail non-image blob');
  }

  const bitmap = await createImageBitmap(blob);
  const { width: w, height: h } = bitmap;

  // object-fit: cover
  const scale = Math.max(size / w, size / h);
  const dw = w * scale;
  const dh = h * scale;
  const dx = (size - dw) / 2;
  const dy = (size - dh) / 2;

  const canvas = new OffscreenCanvas(size, size);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ece7db';
  ctx.fillRect(0, 0, size, size);
  ctx.drawImage(bitmap, dx, dy, dw, dh);
  if (typeof bitmap.close === 'function') bitmap.close();

  return await canvas.convertToBlob({ type: 'image/png' });
}
