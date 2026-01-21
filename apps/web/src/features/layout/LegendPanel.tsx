import { useMemo } from 'react';

import { LAYER_META } from '../legend/layerMeta';
import { LegendScale } from '../legend/LegendScale';
import { useLegendConfig } from '../legend/useLegendConfig';
import { SUPPORTED_LAYER_TYPES, type LayerType } from '../legend/types';
import type { LayerConfig } from '../../state/layerManager';
import { useLayerManagerStore } from '../../state/layerManager';
import { useViewModeStore } from '../../state/viewMode';

export type LegendPanelProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

function pickActiveLayerType(params: {
  selectedLayerId: string | null;
  layers: { id: string; type: LayerType; zIndex: number; visible: boolean }[];
}): LayerType | null {
  if (params.selectedLayerId) {
    const selected = params.layers.find((layer) => layer.id === params.selectedLayerId);
    if (selected) return selected.type;
  }

  const visible = params.layers.filter((layer) => layer.visible);
  if (visible.length === 0) return null;

  const topmost = visible.reduce((acc, next) => (next.zIndex > acc.zIndex ? next : acc));
  return topmost.type;
}

function isLegendLayerType(value: unknown): value is LayerType {
  return SUPPORTED_LAYER_TYPES.includes(value as LayerType);
}

export function LegendPanel({ collapsed, onToggleCollapsed }: LegendPanelProps) {
  const layers = useLayerManagerStore((state) => state.layers);
  const route = useViewModeStore((state) => state.route);

  const selectedLayerId = route.viewModeId === 'layerGlobal' ? route.layerId : null;
  const legendLayers = useMemo(
    () =>
      layers
        .filter(
          (layer): layer is LayerConfig & { type: LayerType } => isLegendLayerType(layer.type),
        )
        .map((layer) => ({
          id: layer.id,
          type: layer.type,
          zIndex: layer.zIndex,
          visible: layer.visible,
        })),
    [layers],
  );

  const layerType = useMemo(
    () =>
      pickActiveLayerType({
        selectedLayerId,
        layers: legendLayers,
      }),
    [legendLayers, selectedLayerId],
  );

  const state = useLegendConfig(layerType);

  return (
    <section
      aria-label="Legend"
      className="rounded-xl border border-slate-400/20 bg-slate-800/80 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-center justify-between gap-3 px-4 py-2">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">图例</div>
          <div className="text-xs text-slate-400">
            {layerType ? LAYER_META[layerType].title : '未选择图层'}
          </div>
        </div>

        <button
          type="button"
          className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          aria-label={collapsed ? '展开图例' : '折叠图例'}
          onClick={onToggleCollapsed}
        >
          {collapsed ? '展开' : '折叠'}
        </button>
      </header>

      {collapsed ? null : (
        <div className="px-4 pb-4">
          {!layerType ? (
            <div className="text-sm text-slate-400">No active layer</div>
          ) : state.status === 'loading' ? (
            <div className="text-sm text-slate-400">Loading…</div>
          ) : state.status === 'error' ? (
            <div className="text-sm text-red-300">{state.message}</div>
          ) : state.status === 'loaded' ? (
            <div>
              <div className="mb-2 flex items-baseline justify-between gap-3">
                <div className="text-sm font-medium text-slate-100">
                  {LAYER_META[layerType].title}
                </div>
                <div className="text-xs text-slate-400">{LAYER_META[layerType].unit}</div>
              </div>
              <LegendScale legend={state.config} />
              <div className="mt-2 flex justify-between text-xs text-slate-400">
                <span>
                  {state.config.labels[0]} {LAYER_META[layerType].unit}
                </span>
                <span>
                  {state.config.labels[state.config.labels.length - 1]} {LAYER_META[layerType].unit}
                </span>
              </div>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
