import { describe, expect, it } from 'vitest';
import { isTileUrl } from './isTileUrl';

describe('isTileUrl', () => {
  it('detects common tiles patterns', () => {
    expect(isTileUrl('https://example.com/tiles/1/2/3.png')).toBe(true);
    expect(isTileUrl('/tiles/1/2/3')).toBe(true);
    expect(isTileUrl('https://example.com/abc/1/2/3.pbf')).toBe(true);
  });

  it('detects z/x/y query params', () => {
    expect(isTileUrl('/api/v1/tiles?z=1&x=2&y=3')).toBe(true);
    expect(isTileUrl('/api/v1/tiles?z=a&x=2&y=3')).toBe(false);
  });

  it('rejects non-tile urls', () => {
    expect(isTileUrl('')).toBe(false);
    expect(isTileUrl('/api/v1/layers')).toBe(false);
  });
});

