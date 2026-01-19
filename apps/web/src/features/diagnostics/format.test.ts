import { describe, expect, it } from 'vitest';
import { formatBytes, formatPercent } from './format';

describe('formatBytes', () => {
  it('handles undefined', () => {
    expect(formatBytes(undefined)).toBe('N/A');
  });

  it('formats bytes/kb/mb/gb', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1023)).toBe('1023 B');
    expect(formatBytes(1024)).toBe('1.0 KB');
    expect(formatBytes(1024 * 1024)).toBe('1.0 MB');
    expect(formatBytes(1024 * 1024 * 1024)).toBe('1.00 GB');
  });
});

describe('formatPercent', () => {
  it('handles denominator <= 0', () => {
    expect(formatPercent(1, 0)).toBe('N/A');
    expect(formatPercent(1, -1)).toBe('N/A');
  });

  it('formats percentage with 1 decimal', () => {
    expect(formatPercent(1, 2)).toBe('50.0%');
    expect(formatPercent(1, 3)).toBe('33.3%');
  });
});

