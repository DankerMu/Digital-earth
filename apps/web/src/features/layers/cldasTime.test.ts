import { describe, expect, it } from 'vitest';

import { alignToMostRecentHourTimeKey, normalizeSnowDepthVariable } from './cldasTime';

describe('alignToMostRecentHourTimeKey', () => {
  it('aligns ISO timestamps to the most recent hour in UTC', () => {
    expect(alignToMostRecentHourTimeKey('2026-01-20T00:00:01Z')).toBe('20260120T000000Z');
    expect(alignToMostRecentHourTimeKey('2026-01-20T10:59:59Z')).toBe('20260120T100000Z');
    expect(alignToMostRecentHourTimeKey('2026-01-20T10:30:00Z')).toBe('20260120T100000Z');
  });

  it('treats timezone-less ISO timestamps as UTC', () => {
    expect(alignToMostRecentHourTimeKey('2026-01-20T10:30:00')).toBe('20260120T100000Z');
  });

  it('aligns YYYYMMDDHH timestamps', () => {
    expect(alignToMostRecentHourTimeKey('2026012010')).toBe('20260120T100000Z');
  });

  it('aligns YYYYMMDDTHHMMSSZ timestamps', () => {
    expect(alignToMostRecentHourTimeKey('20260120T103045Z')).toBe('20260120T100000Z');
  });

  it('returns trimmed input when parsing fails', () => {
    expect(alignToMostRecentHourTimeKey('  not-a-time  ')).toBe('not-a-time');
  });
});

describe('normalizeSnowDepthVariable', () => {
  it('defaults to SNOD when variable is missing', () => {
    expect(normalizeSnowDepthVariable()).toBe('SNOD');
    expect(normalizeSnowDepthVariable('   ')).toBe('SNOD');
  });

  it('maps common snow-depth aliases to SNOD', () => {
    expect(normalizeSnowDepthVariable('snow-depth')).toBe('SNOD');
    expect(normalizeSnowDepthVariable('snow_depth')).toBe('SNOD');
    expect(normalizeSnowDepthVariable('snowdepth')).toBe('SNOD');
    expect(normalizeSnowDepthVariable('snow')).toBe('SNOD');
  });

  it('uppercases other variables', () => {
    expect(normalizeSnowDepthVariable('sd')).toBe('SD');
    expect(normalizeSnowDepthVariable('SNOD')).toBe('SNOD');
  });
});
