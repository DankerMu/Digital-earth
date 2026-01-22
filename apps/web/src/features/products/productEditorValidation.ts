import {
  bboxFromLonLat,
  geoJsonPolygonFromLonLat,
  polygonAreaKm2,
  polygonHasDistinctNonCollinearVertices,
  polygonHasDuplicateVertices,
  polygonHasSelfIntersections,
  polygonMeetsMinimumAreaKm2,
  type BBox,
} from '../../lib/geo';
import type { ProductDraft, ProductHazardDraft } from '../../state/productDraft';

/**
 * Form values for the product editor.
 *
 * Date fields are stored in the `datetime-local` format: `YYYY-MM-DDTHH:mm`.
 * This project treats them as UTC timestamps when converting to/from ISO strings.
 */
export type ProductEditorValues = ProductDraft;

export type ProductEditorHazardSubmit = {
  id: string;
  geometry: { type: 'Polygon'; coordinates: number[][][] };
  bbox: BBox;
  area_km2: number;
};

/**
 * Payload values after normalization.
 *
 * Date fields are ISO 8601 strings in UTC (e.g. `2026-01-01T00:00:00.000Z`).
 */
export type ProductEditorSubmitValues = Omit<ProductDraft, 'issued_at' | 'valid_from' | 'valid_to' | 'hazards'> & {
  issued_at: string;
  valid_from: string;
  valid_to: string;
  hazards: ProductEditorHazardSubmit[];
};

export type ProductEditorErrors = Partial<Record<keyof ProductEditorValues, string>> & {
  form?: string;
};

const MIN_HAZARD_POLYGON_AREA_KM2 = 0.01;

type DateTimeLocalParts = {
  year: number;
  month: number;
  day: number;
  hours: number;
  minutes: number;
  seconds: number;
  milliseconds: number;
};

const DATETIME_LOCAL_RE =
  /^(?<year>\d{4})-(?<month>\d{2})-(?<day>\d{2})T(?<hours>\d{2}):(?<minutes>\d{2})(?::(?<seconds>\d{2})(?:\.(?<milliseconds>\d{1,3}))?)?$/;

function pad2(value: number): string {
  return value.toString().padStart(2, '0');
}

function parseDateTimeLocalParts(value: string): DateTimeLocalParts | null {
  const match = DATETIME_LOCAL_RE.exec(value);
  if (!match?.groups) return null;

  const year = Number(match.groups.year);
  const month = Number(match.groups.month);
  const day = Number(match.groups.day);
  const hours = Number(match.groups.hours);
  const minutes = Number(match.groups.minutes);
  const seconds = match.groups.seconds ? Number(match.groups.seconds) : 0;
  const milliseconds = match.groups.milliseconds ? Number(match.groups.milliseconds.padEnd(3, '0')) : 0;

  if (![year, month, day, hours, minutes, seconds, milliseconds].every(Number.isFinite)) return null;

  if (month < 1 || month > 12) return null;
  if (hours < 0 || hours > 23) return null;
  if (minutes < 0 || minutes > 59) return null;
  if (seconds < 0 || seconds > 59) return null;
  if (milliseconds < 0 || milliseconds > 999) return null;

  const ms = Date.UTC(year, month - 1, day, hours, minutes, seconds, milliseconds);
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return null;
  if (date.getUTCFullYear() !== year) return null;
  if (date.getUTCMonth() + 1 !== month) return null;
  if (date.getUTCDate() !== day) return null;

  return { year, month, day, hours, minutes, seconds, milliseconds };
}

function formatUtcDateTimeLocal(date: Date): string {
  return [
    `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())}`,
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}`,
  ].join('T');
}

export function isoToDatetimeLocal(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const date = new Date(trimmed);
  if (Number.isNaN(date.getTime())) return null;
  return formatUtcDateTimeLocal(date);
}

export function datetimeLocalToIso(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const parts = parseDateTimeLocalParts(trimmed);
  if (!parts) return null;

  const date = new Date(
    Date.UTC(
      parts.year,
      parts.month - 1,
      parts.day,
      parts.hours,
      parts.minutes,
      parts.seconds,
      parts.milliseconds,
    ),
  );

  return date.toISOString();
}

function normalizeText(value: string): string {
  return value.trim();
}

function toEpochMs(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const dateTimeLocalParts = parseDateTimeLocalParts(trimmed);
  if (dateTimeLocalParts) {
    return Date.UTC(
      dateTimeLocalParts.year,
      dateTimeLocalParts.month - 1,
      dateTimeLocalParts.day,
      dateTimeLocalParts.hours,
      dateTimeLocalParts.minutes,
      dateTimeLocalParts.seconds,
      dateTimeLocalParts.milliseconds,
    );
  }

  const ms = new Date(trimmed).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function normalizeProductEditorValues(values: ProductEditorValues): ProductEditorSubmitValues {
  const issuedAtIso = datetimeLocalToIso(values.issued_at);
  const validFromIso = datetimeLocalToIso(values.valid_from);
  const validToIso = datetimeLocalToIso(values.valid_to);

  const normalizedHazards: ProductEditorHazardSubmit[] = values.hazards
    .map((hazard) => {
      if (polygonHasDuplicateVertices(hazard.vertices)) return null;
      if (!polygonHasDistinctNonCollinearVertices(hazard.vertices)) return null;
      if (polygonHasSelfIntersections(hazard.vertices)) return null;
      if (!polygonMeetsMinimumAreaKm2(hazard.vertices, MIN_HAZARD_POLYGON_AREA_KM2)) return null;
      const geometry = geoJsonPolygonFromLonLat(hazard.vertices);
      const bbox = bboxFromLonLat(hazard.vertices);
      const area_km2 = polygonAreaKm2(hazard.vertices);
      if (!geometry || !bbox || area_km2 == null) return null;
      return {
        id: hazard.id,
        geometry,
        bbox,
        area_km2,
      };
    })
    .filter((hazard): hazard is ProductEditorHazardSubmit => hazard != null);

  return {
    title: normalizeText(values.title),
    text: normalizeText(values.text),
    issued_at: issuedAtIso ?? normalizeText(values.issued_at),
    valid_from: validFromIso ?? normalizeText(values.valid_from),
    valid_to: validToIso ?? normalizeText(values.valid_to),
    type: normalizeText(values.type),
    severity: normalizeText(values.severity),
    hazards: normalizedHazards,
  };
}

function hazardStatus(hazard: ProductHazardDraft): string | null {
  if (hazard.vertices.length < 3) return '至少需要 3 个顶点';
  if (polygonHasDuplicateVertices(hazard.vertices)) return '顶点存在重复，请删除重复顶点';
  if (!polygonHasDistinctNonCollinearVertices(hazard.vertices)) return '至少需要 3 个不同且不共线的顶点';
  if (polygonHasSelfIntersections(hazard.vertices)) return '多边形存在自交';
  if (!polygonMeetsMinimumAreaKm2(hazard.vertices, MIN_HAZARD_POLYGON_AREA_KM2))
    return `多边形面积需至少 ${MIN_HAZARD_POLYGON_AREA_KM2} km²`;
  return null;
}

export function validateProductEditor(values: ProductEditorValues): ProductEditorErrors {
  const errors: ProductEditorErrors = {};

  const required: Array<'title' | 'text' | 'issued_at' | 'valid_from' | 'valid_to' | 'type'> = [
    'title',
    'text',
    'issued_at',
    'valid_from',
    'valid_to',
    'type',
  ];

  for (const field of required) {
    if (!normalizeText(values[field])) {
      errors[field] = '此项为必填';
    }
  }

  if (values.hazards.length === 0) {
    errors.hazards = '请至少添加一个风险区域';
  } else {
    const hazardMessages: string[] = [];
    values.hazards.forEach((hazard, index) => {
      const status = hazardStatus(hazard);
      if (!status) return;
      hazardMessages.push(`风险区域 ${index + 1}: ${status}`);
    });
    if (hazardMessages.length > 0) errors.hazards = hazardMessages.join('；');
  }

  const issuedAtMs = toEpochMs(values.issued_at);
  if (normalizeText(values.issued_at) && issuedAtMs == null) {
    errors.issued_at = '请输入合法的时间';
  }

  const validFromMs = toEpochMs(values.valid_from);
  if (normalizeText(values.valid_from) && validFromMs == null) {
    errors.valid_from = '请输入合法的时间';
  }

  const validToMs = toEpochMs(values.valid_to);
  if (normalizeText(values.valid_to) && validToMs == null) {
    errors.valid_to = '请输入合法的时间';
  }

  if (validFromMs != null && validToMs != null && validFromMs >= validToMs) {
    errors.valid_to = '结束时间必须晚于开始时间';
  }

  if (issuedAtMs != null && validFromMs != null && issuedAtMs > validFromMs) {
    errors.issued_at = '发布时间需早于或等于有效开始时间';
  }

  const severity = normalizeText(values.severity);
  if (severity && severity !== 'low' && severity !== 'medium' && severity !== 'high') {
    errors.severity = '严重程度必须为 low / medium / high 或留空';
  }

  return errors;
}
