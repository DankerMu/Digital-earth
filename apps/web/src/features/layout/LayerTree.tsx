import { useMemo } from 'react';

import { useLayerManagerStore } from '../../state/layerManager';
import { useViewModeStore } from '../../state/viewMode';

export type LayerTreeProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

function formatOpacity(opacity: number): string {
  return `${Math.round(opacity * 100)}%`;
}

export function LayerTree({ collapsed, onToggleCollapsed }: LayerTreeProps) {
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

  return (
    <aside
      aria-label="Layer tree"
      className="h-full rounded-xl border border-slate-400/20 bg-slate-800/80 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-center justify-between gap-2 border-b border-slate-400/10 px-3 py-2">
        <div className={collapsed ? 'sr-only' : 'min-w-0'}>
          <div className="text-sm font-semibold text-white">图层</div>
          <div className="text-xs text-slate-400">{visibleCount} 可见</div>
        </div>

        <button
          type="button"
          className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          aria-label={collapsed ? '展开图层树' : '折叠图层树'}
          onClick={onToggleCollapsed}
        >
          {collapsed ? '▶' : '◀'}
        </button>
      </header>

      {collapsed ? null : (
        <div className="max-h-full overflow-auto p-3">
          {layers.length === 0 ? (
            <div className="text-sm text-slate-400">暂无图层</div>
          ) : (
            <ul className="grid gap-2">
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
                          className="h-4 w-4 rounded border-slate-500 bg-slate-900 text-blue-500"
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
                            className="w-full"
                          />
                        </label>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </aside>
  );
}

