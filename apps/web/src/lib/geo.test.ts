import { describe, expect, it } from 'vitest';

import {
  bboxFromLonLat,
  geoJsonPolygonFromLonLat,
  geoJsonRingFromLonLat,
  polygonAreaKm2,
  polygonHasSelfIntersections,
} from './geo';

describe('geo', () => {
  it('bboxFromLonLat returns null for empty input', () => {
    expect(bboxFromLonLat([])).toBeNull();
  });

  it('bboxFromLonLat computes min/max bounds', () => {
    expect(
      bboxFromLonLat([
        { lon: 10, lat: 5 },
        { lon: -1, lat: 8 },
        { lon: 3, lat: -2 },
      ]),
    ).toEqual({ min_x: -1, min_y: -2, max_x: 10, max_y: 8 });
  });

  it('geoJsonRingFromLonLat closes the ring', () => {
    expect(
      geoJsonRingFromLonLat([
        { lon: 0, lat: 0 },
        { lon: 1, lat: 0 },
        { lon: 1, lat: 1 },
      ]),
    ).toEqual([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 0],
    ]);
  });

  it('geoJsonRingFromLonLat preserves already-closed rings', () => {
    expect(
      geoJsonRingFromLonLat([
        { lon: 0, lat: 0 },
        { lon: 1, lat: 0 },
        { lon: 1, lat: 1 },
        { lon: 0, lat: 0 },
      ]),
    ).toEqual([
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 0],
    ]);
  });

  it('geoJsonPolygonFromLonLat returns null when fewer than 3 vertices', () => {
    expect(geoJsonPolygonFromLonLat([])).toBeNull();
    expect(geoJsonPolygonFromLonLat([{ lon: 0, lat: 0 }])).toBeNull();
    expect(
      geoJsonPolygonFromLonLat([
        { lon: 0, lat: 0 },
        { lon: 1, lat: 0 },
      ]),
    ).toBeNull();
  });

  it('geoJsonPolygonFromLonLat creates a Polygon geometry', () => {
    expect(
      geoJsonPolygonFromLonLat([
        { lon: 0, lat: 0 },
        { lon: 1, lat: 0 },
        { lon: 1, lat: 1 },
      ]),
    ).toEqual({
      type: 'Polygon',
      coordinates: [
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ],
    });
  });

  it('polygonAreaKm2 returns null when fewer than 3 vertices', () => {
    expect(polygonAreaKm2([])).toBeNull();
    expect(polygonAreaKm2([{ lon: 0, lat: 0 }])).toBeNull();
    expect(
      polygonAreaKm2([
        { lon: 0, lat: 0 },
        { lon: 1, lat: 0 },
      ]),
    ).toBeNull();
  });

  it('polygonAreaKm2 computes a reasonable area for a 1x1 degree square near the equator', () => {
    const area = polygonAreaKm2([
      { lon: 0, lat: 0 },
      { lon: 1, lat: 0 },
      { lon: 1, lat: 1 },
      { lon: 0, lat: 1 },
    ]);

    expect(area).not.toBeNull();
    // Roughly 12,300 km^2; allow generous bounds to avoid brittle tests.
    expect(area!).toBeGreaterThan(11_000);
    expect(area!).toBeLessThan(14_000);
  });

  it('polygonHasSelfIntersections detects self-crossing polygons', () => {
    expect(
      polygonHasSelfIntersections([
        { lon: 0, lat: 0 },
        { lon: 2, lat: 0 },
        { lon: 2, lat: 2 },
        { lon: 0, lat: 2 },
      ]),
    ).toBe(false);

    // Bow-tie polygon (self-intersecting).
    expect(
      polygonHasSelfIntersections([
        { lon: 0, lat: 0 },
        { lon: 2, lat: 2 },
        { lon: 0, lat: 2 },
        { lon: 2, lat: 0 },
      ]),
    ).toBe(true);
  });
});

