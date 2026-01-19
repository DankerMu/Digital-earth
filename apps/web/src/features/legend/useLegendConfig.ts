import { useEffect, useMemo, useState } from 'react';

import { loadConfig } from '../../config';
import { fetchLegendConfig } from './legendsApi';
import type { LayerType, LegendConfig } from './types';

type LegendLoadState =
  | { status: 'idle'; layerType: null }
  | { status: 'loading'; layerType: LayerType }
  | { status: 'loaded'; layerType: LayerType; config: LegendConfig }
  | { status: 'error'; layerType: LayerType; message: string };

const legendCache = new Map<LayerType, LegendConfig>();

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim() !== '') return error.message;
  return 'Unknown error';
}

function initialState(
  layerType: LayerType | null,
  cached?: LegendConfig,
): LegendLoadState {
  if (!layerType) return { status: 'idle', layerType: null };
  if (cached) return { status: 'loaded', layerType, config: cached };
  return { status: 'loading', layerType };
}

export function useLegendConfig(layerType: LayerType | null): LegendLoadState {
  const cached = useMemo(
    () => (layerType ? legendCache.get(layerType) : undefined),
    [layerType],
  );

  const [state, setState] = useState<LegendLoadState>(() =>
    initialState(layerType, cached),
  );

  const visibleState = useMemo(() => {
    if (state.layerType !== layerType) return initialState(layerType, cached);
    return state;
  }, [cached, layerType, state]);

  useEffect(() => {
    if (!layerType) {
      setState({ status: 'idle', layerType: null });
      return;
    }

    const controller = new AbortController();

    const existing = legendCache.get(layerType);
    if (existing) {
      setState({ status: 'loaded', layerType, config: existing });
    } else {
      setState({ status: 'loading', layerType });
    }

    void (async () => {
      try {
        const { apiBaseUrl } = await loadConfig();
        const legend = await fetchLegendConfig({
          apiBaseUrl,
          layerType,
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        legendCache.set(layerType, legend);
        setState({ status: 'loaded', layerType, config: legend });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({ status: 'error', layerType, message: errorMessage(error) });
      }
    })();

    return () => controller.abort();
  }, [layerType]);

  return visibleState;
}
