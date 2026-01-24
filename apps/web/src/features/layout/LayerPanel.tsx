import { useEffect, useMemo, useState } from 'react';

import { loadConfig, type BasemapProviderMode } from '../../config';
import { CollapsiblePanel } from '../../components/ui/CollapsiblePanel';
import { useLayerManagerStore, type LayerConfig } from '../../state/layerManager';
import { useViewModeStore } from '../../state/viewMode';
import { LAYER_META } from '../legend/layerMeta';
import { LegendScale } from '../legend/LegendScale';
import { SUPPORTED_LAYER_TYPES, type LayerType as LegendLayerType } from '../legend/types';
import { useLegendConfig } from '../legend/useLegendConfig';
import { BasemapSelector } from '../viewer/BasemapSelector';
import { SceneModeToggle } from '../viewer/SceneModeToggle';

export type LayerPanelProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

type MapUiState = {
  loaded: boolean;
  basemapProvider: BasemapProviderMode;
  ionEnabled: boolean;
};

const DEFAULT_MAP_UI_STATE: MapUiState = {
  loaded: false,
  basemapProvider: 'open',
  ionEnabled: false,
};

function formatOpacity(opacity: number): string {
  return `${Math.round(opacity * 100)}%`;
}

function isLegendLayerType(value: unknown): value is LegendLayerType {
  return SUPPORTED_LAYER_TYPES.includes(value as LegendLayerType);
}

function pickActiveLegendLayerType(params: {
  selectedLayerId: string | null;
  layers: { id: string; type: LegendLayerType; zIndex: number; visible: boolean }[];
}): LegendLayerType | null {
  if (params.selectedLayerId) {
    const selected = params.layers.find((layer) => layer.id === params.selectedLayerId);
    if (selected) return selected.type;
  }

  const visible = params.layers.filter((layer) => layer.visible);
  if (visible.length === 0) return null;

  const topmost = visible.reduce((acc, next) => (next.zIndex > acc.zIndex ? next : acc));
  return topmost.type;
}

export function LayerPanel({ collapsed, onToggleCollapsed }: LayerPanelProps) {
  const layers = useLayerManagerStore((state) => state.layers);
  const setLayerVisible = useLayerManagerStore((state) => state.setLayerVisible);
  const setLayerOpacity = useLayerManagerStore((state) => state.setLayerOpacity);

  const route = useViewModeStore((state) => state.route);
  const enterLayerGlobal = useViewModeStore((state) => state.enterLayerGlobal);

  const selectedLayerId = route.viewModeId === 'layerGlobal' ? route.layerId : null;

  const visibleCount = useMemo(
    () => layers.filter((layer) => layer.visible).length,
    [layers],
  );

  const legendLayers = useMemo(
    () =>
      layers
        .filter(
          (layer): layer is LayerConfig & { type: LegendLayerType } => isLegendLayerType(layer.type),
        )
        .map((layer) => ({
          id: layer.id,
          type: layer.type,
          zIndex: layer.zIndex,
          visible: layer.visible,
        })),
    [layers],
  );

  const activeLegendLayerType = useMemo(
    () =>
      pickActiveLegendLayerType({
        selectedLayerId,
        layers: legendLayers,
      }),
    [legendLayers, selectedLayerId],
  );

  const legendState = useLegendConfig(activeLegendLayerType);

  const [mapUiState, setMapUiState] = useState<MapUiState>(DEFAULT_MAP_UI_STATE);

  useEffect(() => {
    let cancelled = false;
    void loadConfig()
      .then((config) => {
        if (cancelled) return;
        const basemapProvider = config.map?.basemapProvider ?? 'open';
        const ionEnabled = Boolean(config.map?.cesiumIonAccessToken);
        setMapUiState({ loaded: true, basemapProvider, ionEnabled });
      })
      .catch(() => {
        if (cancelled) return;
        setMapUiState({ loaded: true, basemapProvider: 'open', ionEnabled: false });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <CollapsiblePanel
      title="图层控制"
      description={`${visibleCount} 可见`}
      collapsed={collapsed}
      onToggleCollapsed={onToggleCollapsed}
      collapsedLabel="展开图层面板"
      expandedLabel="折叠图层面板"
      toggleIcons={{ collapsed: '▶', expanded: '◀' }}
      className="h-full"
      contentClassName="p-4 space-y-4"
    >
      <div className="space-y-4">
        <SceneModeToggle />

        <div className="h-px bg-slate-400/10" />

        {mapUiState.loaded && mapUiState.basemapProvider !== 'open' ? (
          <div className="grid gap-2">
            <div className="text-xs font-semibold tracking-wide text-slate-200">底图</div>
            <div className="text-xs leading-snug text-slate-400">
              当前配置为 {mapUiState.basemapProvider}，底图选择已固定。
            </div>
          </div>
        ) : (
          <BasemapSelector ionEnabled={mapUiState.ionEnabled} />
        )}
      </div>

      <div className="h-px bg-slate-400/10" />

      {layers.length === 0 ? (
        <div className="text-sm text-slate-400">暂无图层</div>
      ) : (
        <ul className="grid list-none gap-2 p-0 m-0">
          {layers.map((layer) => {
            const isSelected = selectedLayerId === layer.id;
            return (
              <li key={layer.id}>
                <button
                  type="button"
                  className={[
                    'group w-full rounded-lg border px-3 py-2 text-left transition-colors',
                    isSelected
                      ? 'border-blue-500/50 bg-blue-500/10'
                      : 'border-slate-400/15 bg-slate-900/20 hover:bg-slate-900/30',
                  ].join(' ')}
                  onClick={() => enterLayerGlobal({ layerId: layer.id })}
                >
                  <div className="flex items-center gap-2">
                    <input
                      aria-label={`显示 ${layer.id}`}
                      type="checkbox"
                      checked={layer.visible}
                      onChange={(event) => setLayerVisible(layer.id, event.target.checked)}
                      onClick={(event) => event.stopPropagation()}
                      className="h-4 w-4 rounded border-slate-500 bg-slate-900 text-blue-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                    />

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium text-slate-100">
                          {layer.id}
                        </span>
                        <span className="text-xs text-slate-400">
                          {formatOpacity(layer.opacity)}
                        </span>
                      </div>
                      <div className="mt-1 text-xs text-slate-500">
                        {layer.type} · {layer.variable}
                      </div>
                    </div>
                  </div>

                  <div className="mt-2">
                    <label className="flex items-center gap-2 text-xs text-slate-400">
                      <span className="w-12 shrink-0">透明度</span>
                      <input
                        aria-label={`透明度 ${layer.id}`}
                        type="range"
                        min={0}
                        max={100}
                        value={Math.round(layer.opacity * 100)}
                        onChange={(event) => {
                          const next = Number(event.target.value) / 100;
                          setLayerOpacity(layer.id, next);
                        }}
                        onClick={(event) => event.stopPropagation()}
                        className="w-full accent-blue-500"
                      />
                    </label>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="h-px bg-slate-400/10" />

      <section aria-label="Legend" className="rounded-lg border border-slate-400/10 bg-slate-900/20 p-3">
        {!activeLegendLayerType ? (
          <div className="text-sm text-slate-400">无可用图例</div>
        ) : legendState.status === 'loading' ? (
          <div className="text-sm text-slate-400">Loading…</div>
        ) : legendState.status === 'error' ? (
          <div className="text-sm text-red-300">{legendState.message}</div>
        ) : legendState.status === 'loaded' ? (
          <div>
            <div className="mb-2 flex items-baseline justify-between gap-3">
              <div className="text-sm font-medium text-slate-100">
                {LAYER_META[activeLegendLayerType].title}
              </div>
              <div className="text-xs text-slate-400">
                {LAYER_META[activeLegendLayerType].unit}
              </div>
            </div>
            <LegendScale legend={legendState.config} />
            <div className="mt-2 flex justify-between text-xs text-slate-400">
              <span>
                {legendState.config.labels[0]} {LAYER_META[activeLegendLayerType].unit}
              </span>
              <span>
                {legendState.config.labels[legendState.config.labels.length - 1]}{' '}
                {LAYER_META[activeLegendLayerType].unit}
              </span>
            </div>
          </div>
        ) : null}
      </section>
    </CollapsiblePanel>
  );
}
