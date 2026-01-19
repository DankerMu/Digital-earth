import type { LayerType, LegendConfig } from './types';
import { parseLegendConfig } from './types';

export async function fetchLegendConfig(options: {
  apiBaseUrl: string;
  layerType: LayerType;
  signal?: AbortSignal;
}): Promise<LegendConfig> {
  const url = new URL('/api/v1/legends', options.apiBaseUrl);
  url.searchParams.set('layer_type', options.layerType);

  const response = await fetch(url.toString(), {
    method: 'GET',
    headers: { Accept: 'application/json' },
    signal: options.signal,
  });

  if (!response.ok) {
    throw new Error(`Failed to load legend: ${response.status}`);
  }

  const data = (await response.json()) as unknown;
  return parseLegendConfig(data);
}

