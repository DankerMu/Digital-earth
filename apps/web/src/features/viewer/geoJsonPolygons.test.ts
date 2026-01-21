import { describe, expect, it } from 'vitest';

import { extractGeoJsonPolygons } from './geoJsonPolygons';

describe('extractGeoJsonPolygons', () => {
  it('returns empty array for non-GeoJSON inputs', () => {
    expect(extractGeoJsonPolygons(null)).toEqual([]);
    expect(extractGeoJsonPolygons('x')).toEqual([]);
    expect(extractGeoJsonPolygons({})).toEqual([]);
    expect(extractGeoJsonPolygons({ type: 123 })).toEqual([]);
  });

  it('extracts polygons from Polygon and MultiPolygon geometries', () => {
    const polygon = extractGeoJsonPolygons({
      type: 'Polygon',
      coordinates: [
        [
          [10, 20],
          [11, 20],
          [11, 21],
          [10, 20],
        ],
        [
          [10.2, 20.2],
          [10.8, 20.2],
          [10.8, 20.8],
        ],
      ],
    });

    expect(polygon).toHaveLength(1);
    expect(polygon[0]).toMatchObject({
      outer: [
        { lon: 10, lat: 20 },
        { lon: 11, lat: 20 },
        { lon: 11, lat: 21 },
        { lon: 10, lat: 20 },
      ],
      holes: [
        [
          { lon: 10.2, lat: 20.2 },
          { lon: 10.8, lat: 20.2 },
          { lon: 10.8, lat: 20.8 },
        ],
      ],
    });

    const multi = extractGeoJsonPolygons({
      type: 'MultiPolygon',
      coordinates: [
        [
          [
            [0, 0],
            [1, 0],
            [1, 1],
          ],
        ],
        [
          [
            [2, 2],
            [3, 2],
            [3, 3],
          ],
        ],
      ],
    });

    expect(multi).toHaveLength(2);
    expect(multi[0]?.outer).toHaveLength(3);
    expect(multi[1]?.outer).toHaveLength(3);
  });

  it('extracts polygons from Feature, FeatureCollection, and GeometryCollection', () => {
    const polygons = extractGeoJsonPolygons({
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [0, 0],
                [1, 0],
                [1, 1],
              ],
            ],
          },
        },
        {
          type: 'Feature',
          geometry: {
            type: 'GeometryCollection',
            geometries: [
              {
                type: 'MultiPolygon',
                coordinates: [
                  [
                    [
                      [2, 2],
                      [3, 2],
                      [3, 3],
                    ],
                  ],
                ],
              },
            ],
          },
        },
      ],
    });

    expect(polygons).toHaveLength(2);
    expect(polygons[0]?.outer[0]).toMatchObject({ lon: 0, lat: 0 });
    expect(polygons[1]?.outer[0]).toMatchObject({ lon: 2, lat: 2 });
  });

  it('ignores invalid rings and coordinates', () => {
    expect(
      extractGeoJsonPolygons({
        type: 'Polygon',
        coordinates: [
          [
            [0, 0],
            [1, 0],
          ],
        ],
      }),
    ).toEqual([]);

    expect(
      extractGeoJsonPolygons({
        type: 'MultiPolygon',
        coordinates: ['not-an-array'],
      }),
    ).toEqual([]);
  });
});

