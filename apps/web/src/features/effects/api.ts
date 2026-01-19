import type { EffectPresetItem } from './types';

function normalizeBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.replace(/\/+$/, '');
}

export async function fetchEffectPresets(
  apiBaseUrl: string,
  options: { signal?: AbortSignal } = {},
): Promise<EffectPresetItem[]> {
  const response = await fetch(
    `${normalizeBaseUrl(apiBaseUrl)}/api/v1/effects/presets`,
    { signal: options.signal },
  );
  if (!response.ok) {
    throw new Error(`Failed to fetch /effects/presets: ${response.status}`);
  }
  return (await response.json()) as EffectPresetItem[];
}

