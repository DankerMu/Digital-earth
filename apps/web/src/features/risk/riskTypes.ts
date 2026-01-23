import type { BBox } from '../products/productsTypes';

export type RiskPOI = {
  id: number;
  name: string;
  type: string;
  lon: number;
  lat: number;
  alt: number | null;
  weight: number;
  tags: string[] | null;
  risk_level: number | 'unknown';
};

export type RiskPOIQueryResponse = {
  page: number;
  page_size: number;
  total: number;
  items: RiskPOI[];
};

export type RiskFactorId = string;

export type RiskFactorEvaluation = {
  id: RiskFactorId;
  value: number;
  score: number;
  weight: number;
  normalized_weight: number;
  contribution: number;
};

export type POIRiskReason = {
  factor_id: RiskFactorId;
  factor_name: string;
  value: number;
  threshold: number;
  contribution: number;
};

export type POIRiskResult = {
  poi_id: number;
  level: number;
  score: number;
  factors: RiskFactorEvaluation[];
  reasons: POIRiskReason[];
};

export type RiskEvaluateSummary = {
  total: number;
  level_counts: Record<string, number>;
  reasons: Record<string, number>;
  max_level: number | null;
  avg_score: number | null;
  duration_ms: number;
};

export type RiskEvaluateResponse = {
  results: POIRiskResult[];
  summary: RiskEvaluateSummary;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function parseOptionalNumber(value: unknown): number | null {
  if (value == null) return null;
  if (typeof value !== 'number') return null;
  return Number.isFinite(value) ? value : null;
}

function parseOptionalStringArray(value: unknown): string[] | null {
  if (value == null) return null;
  if (!Array.isArray(value)) return null;
  const items = value
    .filter((item): item is string => typeof item === 'string')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
  return items.length ? items : null;
}

function parseRiskPoiItem(value: unknown): RiskPOI | null {
  if (!isRecord(value)) return null;
  const id = value.id;
  const name = value.name;
  const type = value.type;
  const lon = value.lon;
  const lat = value.lat;
  const weight = value.weight;

  if (
    !isFiniteNumber(id) ||
    !isNonEmptyString(name) ||
    !isNonEmptyString(type) ||
    !isFiniteNumber(lon) ||
    !isFiniteNumber(lat) ||
    !isFiniteNumber(weight)
  ) {
    return null;
  }

  const alt = parseOptionalNumber(value.alt);
  const risk_level =
    typeof value.risk_level === 'string' && value.risk_level.trim().toLowerCase() === 'unknown'
      ? 'unknown'
      : isFiniteNumber(value.risk_level)
        ? value.risk_level
        : 'unknown';

  return {
    id,
    name: name.trim(),
    type: type.trim(),
    lon,
    lat,
    alt,
    weight,
    tags: parseOptionalStringArray(value.tags),
    risk_level,
  };
}

export function parseRiskPoisQueryResponse(value: unknown): RiskPOIQueryResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid risk POIs response');
  }

  const page = isFiniteNumber(value.page) ? value.page : 1;
  const page_size = isFiniteNumber(value.page_size) ? value.page_size : 100;
  const total = isFiniteNumber(value.total) ? value.total : 0;

  const rawItems = value.items;
  if (!Array.isArray(rawItems)) {
    throw new Error('Invalid risk POIs response');
  }

  const parsedItems = rawItems
    .map(parseRiskPoiItem)
    .filter((item): item is RiskPOI => item != null);

  return {
    page,
    page_size,
    total,
    items: parsedItems,
  };
}

function parseRecordOfNumbers(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {};
  const entries: Array<[string, number]> = [];
  for (const [key, raw] of Object.entries(value)) {
    if (!isFiniteNumber(raw)) continue;
    entries.push([key, raw]);
  }
  return Object.fromEntries(entries);
}

function parseRiskFactorEvaluation(value: unknown): RiskFactorEvaluation | null {
  if (!isRecord(value)) return null;
  const id = value.id;
  const v = value.value;
  const score = value.score;
  const weight = value.weight;
  const normalized_weight = value.normalized_weight;
  const contribution = value.contribution;

  if (
    !isNonEmptyString(id) ||
    !isFiniteNumber(v) ||
    !isFiniteNumber(score) ||
    !isFiniteNumber(weight) ||
    !isFiniteNumber(normalized_weight) ||
    !isFiniteNumber(contribution)
  ) {
    return null;
  }

  return {
    id: id.trim(),
    value: v,
    score,
    weight,
    normalized_weight,
    contribution,
  };
}

function parsePoiRiskReason(value: unknown): POIRiskReason | null {
  if (!isRecord(value)) return null;
  const factor_id = value.factor_id;
  const factor_name = value.factor_name;
  const v = value.value;
  const threshold = value.threshold;
  const contribution = value.contribution;

  if (
    !isNonEmptyString(factor_id) ||
    !isNonEmptyString(factor_name) ||
    !isFiniteNumber(v) ||
    !isFiniteNumber(threshold) ||
    !isFiniteNumber(contribution)
  ) {
    return null;
  }

  return {
    factor_id: factor_id.trim(),
    factor_name: factor_name.trim(),
    value: v,
    threshold,
    contribution,
  };
}

function parsePoiRiskResult(value: unknown): POIRiskResult | null {
  if (!isRecord(value)) return null;

  const poi_id = value.poi_id;
  const level = value.level;
  const score = value.score;
  if (!isFiniteNumber(poi_id) || !isFiniteNumber(level) || !isFiniteNumber(score)) {
    return null;
  }

  const factorsRaw = value.factors;
  const factors = Array.isArray(factorsRaw)
    ? factorsRaw
        .map(parseRiskFactorEvaluation)
        .filter((item): item is RiskFactorEvaluation => item != null)
    : [];

  const reasonsRaw = value.reasons;
  const reasons = Array.isArray(reasonsRaw)
    ? reasonsRaw
        .map(parsePoiRiskReason)
        .filter((item): item is POIRiskReason => item != null)
    : [];

  return {
    poi_id,
    level,
    score,
    factors,
    reasons,
  };
}

export function parseRiskEvaluateResponse(value: unknown): RiskEvaluateResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid risk evaluate response');
  }

  const summaryRaw = value.summary;
  if (!isRecord(summaryRaw)) {
    throw new Error('Invalid risk evaluate response');
  }

  const total = isFiniteNumber(summaryRaw.total) ? summaryRaw.total : 0;
  const duration_ms = isFiniteNumber(summaryRaw.duration_ms) ? summaryRaw.duration_ms : 0;
  const max_level = parseOptionalNumber(summaryRaw.max_level);
  const avg_score = parseOptionalNumber(summaryRaw.avg_score);
  const level_counts = parseRecordOfNumbers(summaryRaw.level_counts);
  const reasons = parseRecordOfNumbers(summaryRaw.reasons);

  const resultsRaw = value.results;
  const results = Array.isArray(resultsRaw)
    ? resultsRaw
        .map(parsePoiRiskResult)
        .filter((item): item is POIRiskResult => item != null)
    : [];

  return {
    results,
    summary: {
      total,
      duration_ms,
      max_level,
      avg_score,
      level_counts,
      reasons,
    },
  };
}

export type RiskSeverity = 'high' | 'medium' | 'low' | 'unknown';

export function riskSeverityForLevel(level: number | 'unknown' | null | undefined): RiskSeverity {
  if (level === 'unknown') return 'unknown';
  if (level == null || !Number.isFinite(level)) return 'unknown';
  const normalized = Math.round(level);
  if (normalized >= 4) return 'high';
  if (normalized >= 3) return 'medium';
  if (normalized >= 1) return 'low';
  return 'unknown';
}

export function formatRiskLevel(level: number | 'unknown' | null | undefined): string {
  if (level === 'unknown') return '--';
  if (level == null || !Number.isFinite(level)) return '--';
  return String(Math.round(level));
}

export function splitBBoxAtDateline(bbox: BBox): BBox[] {
  if (!Number.isFinite(bbox.min_x) || !Number.isFinite(bbox.max_x)) return [bbox];
  if (bbox.min_x <= bbox.max_x) return [bbox];

  return [
    { min_x: bbox.min_x, min_y: bbox.min_y, max_x: 180, max_y: bbox.max_y },
    { min_x: -180, min_y: bbox.min_y, max_x: bbox.max_x, max_y: bbox.max_y },
  ];
}
