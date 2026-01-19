import { describe, expect, it } from 'vitest';

import { parseAttribution, parseAttributionSummary } from './parseAttribution';

const SAMPLE_TEXT = [
  'Attribution (v1.0.0)',
  'Updated: 2026-01-16',
  '',
  'Sources:',
  '- © Cesium — CesiumJS (Cesium GS, Inc. · https://cesium.com/cesiumjs/ · Apache-2.0)',
  '- © ECMWF — ECMWF (European Centre for Medium-Range Weather Forecasts · https://www.ecmwf.int/ · ECMWF Terms of Use)',
  '',
  'Disclaimer:',
  '- 本平台数据仅供参考。',
  '- 具体以官方发布为准。',
  '',
].join('\n');

describe('parseAttribution', () => {
  it('extracts sections from API text', () => {
    const parsed = parseAttribution(SAMPLE_TEXT);
    expect(parsed.title).toBe('Attribution (v1.0.0)');
    expect(parsed.updatedAt).toBe('Updated: 2026-01-16');
    expect(parsed.sources).toHaveLength(2);
    expect(parsed.sources[0]).toContain('CesiumJS');
    expect(parsed.disclaimer).toHaveLength(2);
  });
});

describe('parseAttributionSummary', () => {
  it('builds a compact summary line for the bar', () => {
    expect(parseAttributionSummary(SAMPLE_TEXT)).toBe('© Cesium · © ECMWF');
  });

  it('falls back when text is empty', () => {
    expect(parseAttributionSummary('')).toBe('© Cesium');
  });
});

