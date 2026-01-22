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
    });

    expect(normalized).toEqual({
      title: 'Title',
      type: 'snow',
      severity: '',
      text: 'Body',
      issued_at: '2026-01-01T00:00:00.000Z',
      valid_from: '2026-01-01T00:00:00.000Z',
      valid_to: '2026-01-02T00:00:00.000Z',
    });
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
    });

    expect(errors.severity).toBe('严重程度必须为 low / medium / high 或留空');
  });
});

