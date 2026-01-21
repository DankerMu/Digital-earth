import type { CldasTileUrlTemplateOptions } from './types';

function resolveApiOrigin(apiBaseUrl: string): string {
  const trimmed = apiBaseUrl.trim();
  if (!trimmed) return window.location.origin;

  try {
    const url = new URL(trimmed, window.location.origin);
    return url.origin;
  } catch {
    return trimmed.replace(/\/+$/, '');
  }
}

export function buildCldasTileUrlTemplate(options: CldasTileUrlTemplateOptions): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const variable = encodeURIComponent(options.variable);
  return `${origin}/api/v1/tiles/cldas/${timeKey}/${variable}/{z}/{x}/{y}.png`;
}

export type PrecipitationTileUrlTemplateOptions = Omit<
  CldasTileUrlTemplateOptions,
  'variable'
> & {
  threshold?: number | null;
};

export function buildPrecipitationTileUrlTemplate(
  options: PrecipitationTileUrlTemplateOptions,
): string {
  const origin = resolveApiOrigin(options.apiBaseUrl);
  const timeKey = encodeURIComponent(options.timeKey);
  const base = `${origin}/api/v1/tiles/cldas/${timeKey}/precipitation/{z}/{x}/{y}.png`;

  if (options.threshold == null) return base;
  if (!Number.isFinite(options.threshold)) return base;

  return `${base}?threshold=${encodeURIComponent(String(options.threshold))}`;
}

function normalizeCloudVariable(variable: string | undefined): string {
  const trimmed = variable?.trim() ?? '';
  if (!trimmed) return 'TCC';

  const normalized = trimmed.toLowerCase();
  if (
    normalized === 'tcc' ||
    normalized === 'cloud' ||
    normalized === 'total_cloud_cover' ||
    normalized === 'total-cloud-cover' ||
    normalized === 'total cloud cover' ||
    normalized === 'total_cloud' ||
    normalized === 'total-cloud'
  ) {
    return 'TCC';
  }

  return trimmed.toUpperCase();
}

export type CloudTileUrlTemplateOptions = Omit<CldasTileUrlTemplateOptions, 'variable'> & {
  variable?: string;
};

export function buildCloudTileUrlTemplate(options: CloudTileUrlTemplateOptions): string {
  return buildCldasTileUrlTemplate({
    apiBaseUrl: options.apiBaseUrl,
    timeKey: options.timeKey,
    variable: normalizeCloudVariable(options.variable),
  });
}
