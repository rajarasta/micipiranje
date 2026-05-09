import { jest } from '@jest/globals';
import { parsePaste, screenshotFilename, MAX_ATTACHMENT_BYTES } from '../lib/clipboard.js';

function makeEvent(items) {
  return {
    clipboardData: { items },
    preventDefault: jest.fn()
  };
}

function imageItem(blob) {
  return {
    type: blob.type,
    kind: 'file',
    getAsFile: () => blob
  };
}

function textItem(content) {
  return {
    type: 'text/plain',
    kind: 'string',
    getAsFile: () => null
  };
}

describe('parsePaste', () => {
  test('returns image payload and calls preventDefault when clipboard contains an image', () => {
    const blob = new Blob(['fake'], { type: 'image/png' });
    blob.size === undefined && Object.defineProperty(blob, 'size', { value: 4 });
    const ev = makeEvent([textItem(), imageItem(blob)]);

    const result = parsePaste(ev);

    expect(ev.preventDefault).toHaveBeenCalled();
    expect(result.kind).toBe('image');
    expect(result.blob).toBe(blob);
    expect(result.mimeType).toBe('image/png');
    expect(result.filename).toMatch(/^screenshot-\d{8}-\d{6}\.png$/);
  });

  test('returns null when clipboard has only text', () => {
    const ev = makeEvent([textItem()]);
    expect(parsePaste(ev)).toBeNull();
    expect(ev.preventDefault).not.toHaveBeenCalled();
  });

  test('returns rejected payload when image exceeds size limit', () => {
    const big = new Blob([new Uint8Array(10)], { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: MAX_ATTACHMENT_BYTES + 1 });
    const ev = makeEvent([imageItem(big)]);

    const result = parsePaste(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(result).toEqual({ kind: 'rejected', reason: 'too-large', size: MAX_ATTACHMENT_BYTES + 1 });
  });

  test('uses correct extension based on mimeType', () => {
    const jpg = new Blob(['x'], { type: 'image/jpeg' });
    Object.defineProperty(jpg, 'size', { value: 1 });
    const ev = makeEvent([imageItem(jpg)]);
    expect(parsePaste(ev).filename).toMatch(/\.jpe?g$/);
  });
});

describe('screenshotFilename', () => {
  test('formats timestamp as YYYYMMDD-HHmmss', () => {
    const fixed = new Date('2026-05-09T14:30:22.000Z');
    const name = screenshotFilename('image/png', fixed);
    expect(name).toMatch(/^screenshot-\d{8}-\d{6}\.png$/);
  });

  test('uses local-time components of the provided date', () => {
    const fixed = new Date(2026, 4, 9, 14, 30, 22); // May 9 2026, 14:30:22 LOCAL
    const name = screenshotFilename('image/png', fixed);
    expect(name).toBe('screenshot-20260509-143022.png');
  });
});
