import { describe, expect, it } from 'vitest';

import { parseRgba, rgbaString, withAlpha } from './color';

describe('parseRgba', () => {
  it('parses rgba() strings', () => {
    expect(parseRgba('rgba(10, 20, 30, 0.25)')).toEqual({
      r: 10,
      g: 20,
      b: 30,
      a: 0.25,
    });
  });

  it('rejects invalid rgba() strings', () => {
    expect(() => parseRgba('rgb(0,0,0)')).toThrow(/Invalid rgba/);
    expect(() => parseRgba('rgba(999, 0, 0, 1)')).toThrow(/channel range/);
  });

  it('builds rgba strings and clamps alpha', () => {
    const base = parseRgba('rgba(1, 2, 3, 0.5)');
    expect(rgbaString(withAlpha(base, 2))).toBe('rgba(1, 2, 3, 1)');
  });
});

