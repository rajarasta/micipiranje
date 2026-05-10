import { generateThumbnail } from '../lib/thumbnail.js';
import { jest } from '@jest/globals';

beforeEach(() => {
  globalThis.createImageBitmap = jest.fn(async (blob) => ({
    width: 200,
    height: 100,
    close: jest.fn()
  }));

  class FakeCtx {
    constructor() {
      this.fillStyle = '';
      this.drawImage = jest.fn();
      this.fillRect = jest.fn();
    }
  }

  globalThis.OffscreenCanvas = class {
    constructor(w, h) { this.width = w; this.height = h; this._ctx = new FakeCtx(); }
    getContext() { return this._ctx; }
    async convertToBlob({ type } = {}) {
      // Pretend PNG header bytes
      return new Blob([new Uint8Array([0x89, 0x50, 0x4E, 0x47])], { type: type || 'image/png' });
    }
  };
});

describe('generateThumbnail', () => {
  test('returns a PNG Blob at default size 72', async () => {
    const input = new Blob([new Uint8Array([1,2,3])], { type: 'image/png' });
    const out = await generateThumbnail(input);
    expect(out).toBeInstanceOf(Blob);
    expect(out.type).toBe('image/png');
    expect(out.size).toBeGreaterThan(0);
  });

  test('respects custom size', async () => {
    const input = new Blob([new Uint8Array([1])], { type: 'image/jpeg' });
    const out = await generateThumbnail(input, 32);
    expect(out).toBeInstanceOf(Blob);
  });

  test('rejects non-image blobs', async () => {
    const input = new Blob(['hello'], { type: 'text/plain' });
    await expect(generateThumbnail(input)).rejects.toThrow(/image/i);
  });

  test('rejects null / undefined input', async () => {
    await expect(generateThumbnail(null)).rejects.toThrow();
    await expect(generateThumbnail(undefined)).rejects.toThrow();
  });

  test('uses object-fit:cover math (wide image, square crop)', async () => {
    // Spy: capture drawImage args to verify scaling
    const drawCalls = [];
    globalThis.OffscreenCanvas = class {
      constructor(w, h) { this.width = w; this.height = h; }
      getContext() {
        return {
          fillStyle: '',
          fillRect: () => {},
          drawImage: (...args) => drawCalls.push(args)
        };
      }
      async convertToBlob() { return new Blob([new Uint8Array([1])], { type: 'image/png' }); }
    };
    globalThis.createImageBitmap = jest.fn(async () => ({ width: 200, height: 100, close: () => {} }));

    const input = new Blob([new Uint8Array([1])], { type: 'image/png' });
    await generateThumbnail(input, 72);

    expect(drawCalls.length).toBe(1);
    const [, dx, dy, dw, dh] = drawCalls[0];
    // Wide image: scale = max(72/200, 72/100) = 0.72; dw=144, dh=72
    expect(dw).toBeCloseTo(144, 1);
    expect(dh).toBeCloseTo(72, 1);
    // Centred: dx=(72-144)/2=-36, dy=(72-72)/2=0
    expect(dx).toBeCloseTo(-36, 1);
    expect(dy).toBeCloseTo(0, 1);
  });
});
