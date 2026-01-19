import { useEffect, useMemo, useState } from 'react';

import { loadConfig } from '../../config';
import { fetchLegendConfig } from './legendsApi';
import type { LayerType, LegendConfig } from './types';

type LegendLoadState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'loaded'; config: LegendConfig }
  | { status: 'error'; message: string };

const legendCache = new Map<LayerType, LegendConfig>();

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim() !== '') return error.message;
  return 'Unknown error';
}

export function useLegendConfig(layerType: LayerType | null): LegendLoadState {
  const cached = useMemo(
    () => (layerType ? legendCache.get(layerType) : undefined),
    [layerType],
  );

  const [state, setState] = useState<LegendLoadState>(() => {
    if (cached) return { status: 'loaded', config: cached };
    return layerType ? { status: 'loading' } : { status: 'idle' };
  });

  useEffect(() => {
    if (!layerType) {
      setState({ status: 'idle' });
      return;
    }

    const controller = new AbortController();

    const existing = legendCache.get(layerType);
    if (existing) {
      setState({ status: 'loaded', config: existing });
    } else {
      setState({ status: 'loading' });
    }

    void (async () => {
      try {
        const { apiBaseUrl } = await loadConfig();
        const legend = await fetchLegendConfig({
          apiBaseUrl,
          layerType,
          signal: controller.signal,
        });
        legendCache.set(layerType, legend);
        setState({ status: 'loaded', config: legend });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ status: 'error', message: errorMessage(error) });
      }
    })();

    return () => controller.abort();
  }, [layerType]);

  return state;
}

