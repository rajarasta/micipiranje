export default {
  testEnvironment: 'jsdom',
  // fake-indexeddb/auto only assigns globals; safe in setupFiles. Anything that
  // needs beforeEach/afterEach must go in setupFilesAfterEnv instead.
  // structuredClone polyfill must run BEFORE fake-indexeddb captures it.
  setupFiles: ['<rootDir>/tests/setup-structured-clone.js', 'fake-indexeddb/auto'],
  testMatch: ['<rootDir>/tests/**/*.test.js'],
  transform: {}
};
