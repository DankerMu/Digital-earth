import { describe, expect, it } from 'vitest';

import { buildCldasTileUrlTemplate } from './layersApi';

describe('layersApi', () => {
  it('builds a Cesium url template without encoding placeholders', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test/',
      timeKey: '2024-01-15T00:00:00Z',
      variable: 'TMP',
    });

    expect(url).toBe(
      'http://api.test/api/v1/tiles/cldas/2024-01-15T00%3A00%3A00Z/TMP/{z}/{x}/{y}.png',
    );
    expect(url).toContain('{z}');
    expect(url).toContain('{x}');
    expect(url).toContain('{y}');
    expect(url).not.toContain('%7Bz%7D');
  });

  it('drops any apiBaseUrl pathname when joining absolute api routes', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test/some/prefix/',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url).toBe('http://api.test/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png');
    expect(url).not.toContain('/some/prefix/');
  });

  it('falls back to window origin when apiBaseUrl is blank', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: '   ',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url.startsWith(window.location.origin)).toBe(true);
  });

  it('falls back to string trimming when apiBaseUrl cannot be parsed', () => {
    const url = buildCldasTileUrlTemplate({
      apiBaseUrl: 'http://api.test:bad/',
      timeKey: '2024011500',
      variable: 'TMP',
    });

    expect(url).toBe(
      'http://api.test:bad/api/v1/tiles/cldas/2024011500/TMP/{z}/{x}/{y}.png',
    );
  });
});
