import { splitMatches } from '../lib/search.js';

describe('splitMatches', () => {
  test('empty query returns single non-hi run', () => {
    expect(splitMatches('hello world', '')).toEqual([{ text: 'hello world', hi: false }]);
  });

  test('empty text returns empty array', () => {
    expect(splitMatches('', 'foo')).toEqual([]);
  });

  test('single match in middle splits into 3 runs', () => {
    expect(splitMatches('hello world', 'world')).toEqual([
      { text: 'hello ', hi: false },
      { text: 'world',  hi: true  }
    ]);
  });

  test('match at start', () => {
    expect(splitMatches('hello world', 'hello')).toEqual([
      { text: 'hello', hi: true },
      { text: ' world', hi: false }
    ]);
  });

  test('multiple matches', () => {
    expect(splitMatches('aXbXc', 'X')).toEqual([
      { text: 'a', hi: false },
      { text: 'X', hi: true  },
      { text: 'b', hi: false },
      { text: 'X', hi: true  },
      { text: 'c', hi: false }
    ]);
  });

  test('case-insensitive matching, preserves original case', () => {
    expect(splitMatches('Hello WORLD', 'world')).toEqual([
      { text: 'Hello ', hi: false },
      { text: 'WORLD',  hi: true  }
    ]);
  });

  test('non-matching query returns single non-hi run', () => {
    expect(splitMatches('hello', 'zzz')).toEqual([{ text: 'hello', hi: false }]);
  });

  test('escapes regex meta characters in query', () => {
    expect(splitMatches('a.b.c', '.')).toEqual([
      { text: 'a', hi: false },
      { text: '.', hi: true  },
      { text: 'b', hi: false },
      { text: '.', hi: true  },
      { text: 'c', hi: false }
    ]);
  });
});
