import { describe, expect, it } from 'vitest';

import { BASEMAPS, DEFAULT_BASEMAP_ID, getBasemapById, isBasemapId } from './basemaps';

describe('basemaps config', () => {
  it('exposes a valid default basemap id', () => {
    expect(isBasemapId(DEFAULT_BASEMAP_ID)).toBe(true);
    expect(getBasemapById(DEFAULT_BASEMAP_ID)?.id).toBe(DEFAULT_BASEMAP_ID);
  });

  it('rejects unknown ids', () => {
    expect(isBasemapId('nope')).toBe(false);
    expect(getBasemapById('nope')).toBeUndefined();
  });

  it('includes at least one WMTS and one URL template option', () => {
    expect(BASEMAPS.some((basemap) => basemap.kind === 'wmts')).toBe(true);
    expect(BASEMAPS.some((basemap) => basemap.kind === 'url-template')).toBe(true);
    expect(BASEMAPS.some((basemap) => basemap.kind === 'ion')).toBe(true);
  });
});
