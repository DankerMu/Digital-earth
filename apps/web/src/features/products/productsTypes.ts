export type BBox = {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
};

export type ProductHazardSummary = {
  severity: string;
  geometry: unknown;
  bbox: BBox;
};

export type ProductSummary = {
  id: number;
  title: string;
  hazards: ProductHazardSummary[];
};

export type ProductsQueryResponse = {
  page: number;
  page_size: number;
  total: number;
  items: ProductSummary[];
};

export type ProductHazardDetail = {
  id: number;
  severity: string;
  geometry: unknown;
  bbox: BBox;
  valid_from: string;
  valid_to: string;
};

export type ProductDetail = {
  id: number;
  title: string;
  text: string | null;
  issued_at: string;
  valid_from: string;
  valid_to: string;
  version: number;
  status: 'draft' | 'published' | (string & {});
  hazards: ProductHazardDetail[];
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

function parseBBox(value: unknown): BBox {
  if (!isRecord(value)) {
    throw new Error('Invalid bbox');
  }

  const min_x = value.min_x;
  const min_y = value.min_y;
  const max_x = value.max_x;
  const max_y = value.max_y;

  if (
    !isFiniteNumber(min_x) ||
    !isFiniteNumber(min_y) ||
    !isFiniteNumber(max_x) ||
    !isFiniteNumber(max_y)
  ) {
    throw new Error('Invalid bbox');
  }

  return { min_x, min_y, max_x, max_y };
}

function parseProductHazardSummary(value: unknown): ProductHazardSummary | null {
  if (!isRecord(value)) return null;

  const severity = value.severity;
  if (!isNonEmptyString(severity)) return null;

  try {
    return {
      severity: severity.trim(),
      geometry: value.geometry,
      bbox: parseBBox(value.bbox),
    };
  } catch {
    return null;
  }
}

function parseProductSummary(value: unknown): ProductSummary | null {
  if (!isRecord(value)) return null;

  const id = value.id;
  const title = value.title;
  if (!isFiniteNumber(id) || !isNonEmptyString(title)) return null;

  const hazardsRaw = value.hazards;
  const hazards = Array.isArray(hazardsRaw)
    ? hazardsRaw
        .map(parseProductHazardSummary)
        .filter((hazard): hazard is ProductHazardSummary => hazard != null)
    : [];

  return {
    id,
    title: title.trim(),
    hazards,
  };
}

export function parseProductsQueryResponse(value: unknown): ProductsQueryResponse {
  if (!isRecord(value)) {
    throw new Error('Invalid products response');
  }

  const page = isFiniteNumber(value.page) ? value.page : 1;
  const page_size = isFiniteNumber(value.page_size) ? value.page_size : 50;
  const total = isFiniteNumber(value.total) ? value.total : 0;

  const rawItems = value.items;
  if (!Array.isArray(rawItems)) {
    throw new Error('Invalid products response');
  }

  const parsedItems = rawItems
    .map(parseProductSummary)
    .filter((item): item is ProductSummary => item != null);

  return {
    page,
    page_size,
    total,
    items: parsedItems,
  };
}

function parseOptionalString(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseDateTime(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Invalid datetime');
  const trimmed = value.trim();
  if (trimmed.length === 0) throw new Error('Invalid datetime');
  return trimmed;
}

function parseProductHazardDetail(value: unknown): ProductHazardDetail | null {
  if (!isRecord(value)) return null;

  const id = value.id;
  const severity = value.severity;
  if (!isFiniteNumber(id) || !isNonEmptyString(severity)) return null;

  try {
    return {
      id,
      severity: severity.trim(),
      geometry: value.geometry,
      bbox: parseBBox(value.bbox),
      valid_from: parseDateTime(value.valid_from),
      valid_to: parseDateTime(value.valid_to),
    };
  } catch {
    return null;
  }
}

export function parseProductDetailResponse(value: unknown): ProductDetail {
  if (!isRecord(value)) {
    throw new Error('Invalid product detail');
  }

  const id = value.id;
  const title = value.title;
  if (!isFiniteNumber(id) || !isNonEmptyString(title)) {
    throw new Error('Invalid product detail');
  }

  const issued_at = parseDateTime(value.issued_at);
  const valid_from = parseDateTime(value.valid_from);
  const valid_to = parseDateTime(value.valid_to);
  const version = isFiniteNumber(value.version) ? value.version : 1;

  const statusRaw = value.status;
  const status = isNonEmptyString(statusRaw) ? statusRaw.trim() : 'published';

  const hazardsRaw = value.hazards;
  const hazards = Array.isArray(hazardsRaw)
    ? hazardsRaw
        .map(parseProductHazardDetail)
        .filter((hazard): hazard is ProductHazardDetail => hazard != null)
    : [];

  return {
    id,
    title: title.trim(),
    text: parseOptionalString(value.text),
    issued_at,
    valid_from,
    valid_to,
    version,
    status,
    hazards,
  };
}
