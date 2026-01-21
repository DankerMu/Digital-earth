const HOUR_MS = 60 * 60 * 1000;

const ALIGN_CACHE_MAX_ENTRIES = 200;
const alignedHourCache = new Map<string, string>();

function pad2(value: number): string {
  return String(value).padStart(2, '0');
}

function formatCldasTimeKeyUtc(date: Date): string {
  const year = date.getUTCFullYear();
  const month = pad2(date.getUTCMonth() + 1);
  const day = pad2(date.getUTCDate());
  const hour = pad2(date.getUTCHours());
  return `${year}${month}${day}T${hour}0000Z`;
}

function parseCldasTimeKey(value: string): Date | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  if (/^\d{10}$/.test(trimmed)) {
    const year = Number(trimmed.slice(0, 4));
    const month = Number(trimmed.slice(4, 6));
    const day = Number(trimmed.slice(6, 8));
    const hour = Number(trimmed.slice(8, 10));
    const ms = Date.UTC(year, month - 1, day, hour, 0, 0);
    const parsed = new Date(ms);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  if (/^\d{8}T\d{6}Z$/.test(trimmed)) {
    const year = Number(trimmed.slice(0, 4));
    const month = Number(trimmed.slice(4, 6));
    const day = Number(trimmed.slice(6, 8));
    const hour = Number(trimmed.slice(9, 11));
    const minute = Number(trimmed.slice(11, 13));
    const second = Number(trimmed.slice(13, 15));
    const ms = Date.UTC(year, month - 1, day, hour, minute, second);
    const parsed = new Date(ms);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }

  const parsed = new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function writeAlignedCache(key: string, value: string) {
  alignedHourCache.delete(key);
  alignedHourCache.set(key, value);
  while (alignedHourCache.size > ALIGN_CACHE_MAX_ENTRIES) {
    const oldest = alignedHourCache.keys().next().value as string | undefined;
    if (!oldest) break;
    alignedHourCache.delete(oldest);
  }
}

export function alignToMostRecentHourTimeKey(timeKey: string): string {
  const trimmed = timeKey.trim();
  if (!trimmed) return '';

  const cached = alignedHourCache.get(trimmed);
  if (cached) return cached;

  const parsed = parseCldasTimeKey(trimmed);
  if (!parsed) return trimmed;

  const alignedMs = Math.floor(parsed.getTime() / HOUR_MS) * HOUR_MS;
  const aligned = new Date(alignedMs);
  const formatted = formatCldasTimeKeyUtc(aligned);
  writeAlignedCache(trimmed, formatted);
  return formatted;
}

export function normalizeSnowDepthVariable(variable?: string): string {
  const trimmed = variable?.trim() ?? '';
  if (!trimmed) return 'SNOD';

  const normalized = trimmed.toLowerCase();
  if (
    normalized === 'snow-depth' ||
    normalized === 'snow_depth' ||
    normalized === 'snowdepth' ||
    normalized === 'snow depth' ||
    normalized === 'snow' ||
    normalized === 'snod'
  ) {
    return 'SNOD';
  }

  return trimmed.toUpperCase();
}

