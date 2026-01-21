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

