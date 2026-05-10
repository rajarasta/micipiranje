import { derivedTagFilters } from '../lib/tags.js';

describe('derivedTagFilters', () => {
  test('returns Sve + top-4 by count desc, alpha tiebreak', () => {
    const notes = [
      { tags: ['posao', 'dev'] },
      { tags: ['posao', 'osobno'] },
      { tags: ['posao'] },
      { tags: ['dizajn', 'dev'] },
      { tags: [] }
    ];
    expect(derivedTagFilters(notes)).toEqual(['Sve', 'posao', 'dev', 'dizajn', 'osobno']);
  });

  test('top defaults to 4', () => {
    const notes = [
      { tags: ['a'] }, { tags: ['b'] }, { tags: ['c'] }, { tags: ['d'] }, { tags: ['e'] }, { tags: ['f'] }
    ];
    const result = derivedTagFilters(notes);
    expect(result.length).toBe(5);            // Sve + 4
    expect(result[0]).toBe('Sve');
  });

  test('respects custom top', () => {
    const notes = [
      { tags: ['a'] }, { tags: ['b'] }, { tags: ['c'] }
    ];
    expect(derivedTagFilters(notes, 2)).toEqual(['Sve', 'a', 'b']);
  });

  test('handles missing or empty tag arrays', () => {
    expect(derivedTagFilters([])).toEqual(['Sve']);
    expect(derivedTagFilters([{}, { tags: undefined }, { tags: null }])).toEqual(['Sve']);
  });

  test('alphabetical tiebreaker on equal counts', () => {
    const notes = [
      { tags: ['banana'] }, { tags: ['apple'] }, { tags: ['cherry'] }
    ];
    expect(derivedTagFilters(notes)).toEqual(['Sve', 'apple', 'banana', 'cherry']);
  });
});
