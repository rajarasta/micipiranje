export default {
  testEnvironment: 'jsdom',
  // fake-indexeddb/auto only assigns globals; safe in setupFiles. Anything that
  // needs beforeEach/afterEach must go in setupFilesAfterEnv instead.
  setupFiles: ['fake-indexeddb/auto'],
  testMatch: ['<rootDir>/tests/**/*.test.js'],
  transform: {}
};
