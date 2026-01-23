export type VolumeApiBBox = {
  west: number;
  south: number;
  east: number;
  north: number;
  bottom: number;
  top: number;
};

export type VolumeApiParams = {
  apiBaseUrl: string;
  bbox: VolumeApiBBox;
  levels: number[];
  res: number;
  validTime?: string;
};

function resolveApiOrigin(apiBaseUrl: string): string {
  const trimmed = apiBaseUrl.trim();
  const fallbackOrigin =
    typeof window !== 'undefined' && window.location?.origin ? window.location.origin : '';

  if (!trimmed) return fallbackOrigin || 'http://localhost';

  try {
    const url = new URL(trimmed, fallbackOrigin || 'http://localhost');
    return url.origin;
  } catch {
    return trimmed.replace(/\/+$/, '');
  }
}

function normalizeBBox(bbox: VolumeApiBBox): VolumeApiBBox {
  const values = [bbox.west, bbox.south, bbox.east, bbox.north, bbox.bottom, bbox.top];
  if (!values.every((value) => typeof value === 'number' && Number.isFinite(value))) {
    throw new Error('Volume API bbox must contain finite numbers');
  }
  return bbox;
}

function normalizeLevels(levels: number[]): number[] {
  if (!Array.isArray(levels)) {
    throw new Error('Volume API levels must be an array');
  }

  const normalized: number[] = [];
  const seen = new Set<number>();
  for (const entry of levels) {
    if (typeof entry !== 'number' || !Number.isFinite(entry)) continue;
    const rounded = Math.round(entry);
    if (rounded <= 0) continue;
    if (seen.has(rounded)) continue;
    seen.add(rounded);
    normalized.push(rounded);
  }

  if (normalized.length === 0) {
    throw new Error('Volume API levels must include at least one valid level');
  }

  return normalized;
}

function normalizeRes(res: number): number {
  if (typeof res !== 'number' || !Number.isFinite(res) || res <= 0) {
    throw new Error('Volume API res must be a positive number');
  }
  return res;
}

export async function fetchVolumePack(
  params: VolumeApiParams,
  options?: { signal?: AbortSignal },
): Promise<ArrayBuffer> {
  const origin = resolveApiOrigin(params.apiBaseUrl);
  const bbox = normalizeBBox(params.bbox);
  const levels = normalizeLevels(params.levels);
  const res = normalizeRes(params.res);

  const url = new URL(`${origin}/api/v1/volume`);
  url.searchParams.set(
    'bbox',
    `${bbox.west},${bbox.south},${bbox.east},${bbox.north},${bbox.bottom},${bbox.top}`,
  );
  url.searchParams.set('levels', levels.join(','));
  url.searchParams.set('res', String(res));
  if (params.validTime) url.searchParams.set('valid_time', params.validTime);

  const response = await fetch(url.toString(), { signal: options?.signal });
  if (!response.ok) {
    throw new Error(`Volume API error: ${response.status}`);
  }
  return response.arrayBuffer();
}
