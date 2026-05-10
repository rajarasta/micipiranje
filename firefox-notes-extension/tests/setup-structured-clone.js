import structuredCloneImpl from '@ungap/structured-clone';
import { randomUUID } from 'node:crypto';

// jsdom + Node's native structuredClone do not preserve jsdom Blob instances
// (they round-trip to plain Object). Wrap whichever structuredClone we end up
// with so Blobs survive the IndexedDB round-trip in tests, while delegating
// all other types (Date, Map, Set, TypedArray, ...) to the base implementation.
const baseClone = typeof globalThis.structuredClone === 'function'
  ? globalThis.structuredClone.bind(globalThis)
  : structuredCloneImpl;

function containsBlob(value, seen) {
  if (value === null || typeof value !== 'object') return false;
  if (value instanceof Blob) return true;
  if (seen.has(value)) return false;
  seen.add(value);
  if (Array.isArray(value)) {
    for (const v of value) if (containsBlob(v, seen)) return true;
    return false;
  }
  // Only recurse plain object-shaped containers; leave exotic types to baseClone.
  const proto = Object.getPrototypeOf(value);
  if (proto === Object.prototype || proto === null) {
    for (const k of Object.keys(value)) if (containsBlob(value[k], seen)) return true;
  }
  return false;
}

function cloneWithBlobs(value, seen) {
  if (value instanceof Blob) {
    return new Blob([value], { type: value.type });
  }
  if (value === null || typeof value !== 'object') return value;
  if (seen.has(value)) return seen.get(value);
  if (Array.isArray(value)) {
    const out = [];
    seen.set(value, out);
    for (const v of value) out.push(cloneWithBlobs(v, seen));
    return out;
  }
  const proto = Object.getPrototypeOf(value);
  if (proto === Object.prototype || proto === null) {
    const out = {};
    seen.set(value, out);
    for (const k of Object.keys(value)) out[k] = cloneWithBlobs(value[k], seen);
    return out;
  }
  // Exotic type with no Blob inside — defer to base (preserves Date/Map/etc.).
  return baseClone(value);
}

globalThis.structuredClone = (value) => {
  if (!containsBlob(value, new Set())) return baseClone(value);
  return cloneWithBlobs(value, new Map());
};

if (typeof globalThis.crypto !== 'object' || typeof globalThis.crypto.randomUUID !== 'function') {
  if (!globalThis.crypto) globalThis.crypto = {};
  if (typeof globalThis.crypto.randomUUID !== 'function') {
    globalThis.crypto.randomUUID = randomUUID;
  }
}

// jsdom's Blob lacks .text() / .arrayBuffer(). Polyfill them via FileReader so
// export tests (and any future code path that round-trips Blob -> text/bytes)
// work in the test environment.
if (typeof Blob !== 'undefined') {
  if (typeof Blob.prototype.text !== 'function') {
    Blob.prototype.text = function () {
      return new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(String(fr.result || ''));
        fr.onerror = () => reject(fr.error);
        fr.readAsText(this);
      });
    };
  }
  if (typeof Blob.prototype.arrayBuffer !== 'function') {
    Blob.prototype.arrayBuffer = function () {
      return new Promise((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => resolve(fr.result);
        fr.onerror = () => reject(fr.error);
        fr.readAsArrayBuffer(this);
      });
    };
  }
}
