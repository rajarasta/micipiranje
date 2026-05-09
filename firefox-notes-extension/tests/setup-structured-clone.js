import structuredCloneImpl from '@ungap/structured-clone';
import { randomUUID } from 'node:crypto';

if (typeof globalThis.structuredClone !== 'function') {
  globalThis.structuredClone = structuredCloneImpl;
}

if (typeof globalThis.crypto !== 'object' || typeof globalThis.crypto.randomUUID !== 'function') {
  if (!globalThis.crypto) globalThis.crypto = {};
  if (typeof globalThis.crypto.randomUUID !== 'function') {
    globalThis.crypto.randomUUID = randomUUID;
  }
}
