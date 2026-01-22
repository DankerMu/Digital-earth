import { describe, expect, it } from 'vitest';

import {
  datetimeLocalToIso,
  isoToDatetimeLocal,
  normalizeProductEditorValues,
  validateProductEditor,
} from './productEditorValidation';

describe('productEditorValidation', () => {
  it('converts datetime-local strings to ISO (UTC)', () => {
    expect(datetimeLocalToIso('2026-01-01T00:00')).toBe('2026-01-01T00:00:00.000Z');
    expect(datetimeLocalToIso('not-a-date')).toBeNull();
  });

  it('converts ISO strings to datetime-local (UTC)', () => {
    expect(isoToDatetimeLocal('2026-01-01T00:00:00Z')).toBe('2026-01-01T00:00');
    expect(isoToDatetimeLocal('not-a-date')).toBeNull();
  });

  it('normalizes datetime-local fields into ISO strings', () => {
    const normalized = normalizeProductEditorValues({
      title: '  Title  ',
      type: ' snow ',
      severity: '',
      text: ' Body ',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T00:00',
      valid_to: '2026-01-02T00:00',
      hazards: [
        {
          id: 'h1',
          vertices: [
            { lon: 0, lat: 0 },
            { lon: 1, lat: 0 },
            { lon: 1, lat: 1 },
          ],
        },
      ],
    });

    expect(normalized).toMatchObject({
      title: 'Title',
      type: 'snow',
      severity: '',
      text: 'Body',
      issued_at: '2026-01-01T00:00:00.000Z',
      valid_from: '2026-01-01T00:00:00.000Z',
      valid_to: '2026-01-02T00:00:00.000Z',
      hazards: [
        {
          id: 'h1',
          bbox: { min_x: 0, min_y: 0, max_x: 1, max_y: 1 },
          geometry: {
            type: 'Polygon',
            coordinates: [
              [
                [0, 0],
                [1, 0],
                [1, 1],
                [0, 0],
              ],
            ],
          },
        },
      ],
    });
    expect(normalized.hazards[0]!.area_km2).toBeTypeOf('number');
    expect(normalized.hazards[0]!.area_km2).toBeGreaterThan(0);
  });

  it('validates severity values', () => {
    const errors = validateProductEditor({
      title: 'Title',
      type: 'snow',
      severity: 'oops',
      text: 'Body',
      issued_at: '2026-01-01T00:00',
      valid_from: '2026-01-01T00:00',
      valid_to: '2026-01-02T00:00',
      hazards: [
        {
          id: 'h1',
          vertices: [
            { lon: 0, lat: 0 },
            { lon: 1, lat: 0 },
            { lon: 1, lat: 1 },
          ],
        },
      ],
    });

    expect(errors.severity).toBe('严重程度必须为 low / medium / high 或留空');
  });

  it('validates hazard polygons', () => {
    expect(
      validateProductEditor({
        title: 'Title',
        type: 'snow',
        severity: '',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T00:00',
        valid_to: '2026-01-02T00:00',
        hazards: [],
      }).hazards,
    ).toBe('请至少添加一个风险区域');

    expect(
      validateProductEditor({
        title: 'Title',
        type: 'snow',
        severity: '',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T00:00',
        valid_to: '2026-01-02T00:00',
        hazards: [{ id: 'h1', vertices: [{ lon: 0, lat: 0 }] }],
      }).hazards,
    ).toContain('至少需要 3 个顶点');

    expect(
      validateProductEditor({
        title: 'Title',
        type: 'snow',
        severity: '',
        text: 'Body',
        issued_at: '2026-01-01T00:00',
        valid_from: '2026-01-01T00:00',
        valid_to: '2026-01-02T00:00',
        hazards: [
          {
            id: 'h1',
            vertices: [
              { lon: 0, lat: 0 },
              { lon: 2, lat: 2 },
              { lon: 0, lat: 2 },
              { lon: 2, lat: 0 },
            ],
          },
        ],
      }).hazards,
    ).toContain('多边形存在自交');
  });
});
