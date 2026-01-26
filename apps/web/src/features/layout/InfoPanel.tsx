import { useEffect, useMemo, useState } from 'react';

import { CollapsiblePanel } from '../../components/ui/CollapsiblePanel';
import { loadConfig } from '../../config';
import { useLayerManagerStore } from '../../state/layerManager';
import { DEFAULT_LEVEL_KEY, useTimeStore } from '../../state/time';
import { useViewerStatsStore } from '../../state/viewerStats';
import { useViewModeStore } from '../../state/viewMode';
import { getEcmwfRunVars } from '../catalog/ecmwfCatalogApi';
import { EventListPanel } from '../products/EventListPanel';
import PerformanceModeToggle from '../settings/PerformanceModeToggle';
import OsmBuildingsToggle from '../settings/OsmBuildingsToggle';
import RealLightingToggle from '../settings/RealLightingToggle';

export type InfoPanelProps = {
  collapsed: boolean;
  onToggleCollapsed: () => void;
};

function routeSummary(route: ReturnType<typeof useViewModeStore.getState>['route']): string {
  switch (route.viewModeId) {
    case 'global':
      return '全局';
    case 'local':
      return `局地 (${route.lat.toFixed(3)}, ${route.lon.toFixed(3)})`;
    case 'event':
      return `事件 (${route.productId})`;
    case 'layerGlobal':
      return `图层 (${route.layerId})`;
  }
}

export function InfoPanel({ collapsed, onToggleCollapsed }: InfoPanelProps) {
  const [tab, setTab] = useState<'current' | 'forecast' | 'history' | 'settings'>('current');

  const route = useViewModeStore((state) => state.route);
  const canGoBack = useViewModeStore((state) => state.canGoBack);
  const goBack = useViewModeStore((state) => state.goBack);

  const layers = useLayerManagerStore((state) => state.layers);
  const fps = useViewerStatsStore((state) => state.fps);

  const runTimeKey = useTimeStore((state) => state.runTimeKey);
  const levelKey = useTimeStore((state) => state.levelKey);
  const setLevelKey = useTimeStore((state) => state.setLevelKey);

  const [forecastLevels, setForecastLevels] = useState<string[]>([DEFAULT_LEVEL_KEY]);
  const [forecastStatus, setForecastStatus] = useState<'idle' | 'loading' | 'loaded' | 'error'>(
    'idle',
  );
  const [forecastError, setForecastError] = useState<string | null>(null);

  const selectedLayer = useMemo(() => {
    if (route.viewModeId !== 'layerGlobal') return null;
    return layers.find((layer) => layer.id === route.layerId) ?? null;
  }, [layers, route]);

  useEffect(() => {
    if (tab !== 'forecast') return;
    if (!runTimeKey) return;

    let cancelled = false;
    const controller = new AbortController();
    setForecastStatus('loading');
    setForecastError(null);

    void loadConfig()
      .then((config) =>
        getEcmwfRunVars({
          apiBaseUrl: config.apiBaseUrl,
          runTimeKey,
          signal: controller.signal,
        }),
      )
      .then((response) => {
        if (cancelled) return;
        const levels = response.levels.length > 0 ? response.levels : [DEFAULT_LEVEL_KEY];
        setForecastLevels(levels);
        setForecastStatus('loaded');

        const currentLevelKey = useTimeStore.getState().levelKey.trim().toLowerCase();
        if (!levels.some((item) => item.trim().toLowerCase() === currentLevelKey)) {
          const first = levels[0]?.trim();
          if (first) setLevelKey(first);
        }
      })
      .catch((error) => {
        if (cancelled) return;
        console.warn('[InfoPanel] failed to load ECMWF run vars', error);
        setForecastStatus('error');
        setForecastError('加载预报配置失败');
        setForecastLevels([DEFAULT_LEVEL_KEY]);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runTimeKey, setLevelKey, tab]);

  return (
    <aside aria-label="Info panel" className="h-full">
      <CollapsiblePanel
        title="信息面板"
        description={
          <span data-testid="view-mode-indicator" data-view-mode={route.viewModeId}>
            {routeSummary(route)}
          </span>
        }
        collapsed={collapsed}
        onToggleCollapsed={onToggleCollapsed}
        collapsedLabel="展开信息面板"
        expandedLabel="折叠信息面板"
        toggleIcons={{ collapsed: '◀', expanded: '▶' }}
        actions={
          collapsed ? null : (
            <button
              type="button"
              className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
              aria-label="返回上一视图"
              disabled={!canGoBack}
              onClick={() => goBack()}
            >
              返回
            </button>
          )
        }
        className="h-full"
        contentClassName="p-0 overflow-hidden"
      >
        <div className="flex h-full flex-col">
          <div className="flex border-b border-slate-400/10">
            <button
              type="button"
              className={[
                'flex-1 px-3 py-2 text-sm',
                tab === 'current'
                  ? 'border-b-2 border-blue-500 text-blue-300'
                  : 'text-slate-400 hover:text-slate-200',
              ].join(' ')}
              onClick={() => setTab('current')}
            >
              当前
            </button>
            <button
              type="button"
              className={[
                'flex-1 px-3 py-2 text-sm',
                tab === 'forecast'
                  ? 'border-b-2 border-blue-500 text-blue-300'
                  : 'text-slate-400 hover:text-slate-200',
              ].join(' ')}
              onClick={() => setTab('forecast')}
            >
              预报
            </button>
            <button
              type="button"
              className={[
                'flex-1 px-3 py-2 text-sm',
                tab === 'history'
                  ? 'border-b-2 border-blue-500 text-blue-300'
                  : 'text-slate-400 hover:text-slate-200',
              ].join(' ')}
              onClick={() => setTab('history')}
            >
              历史
            </button>
            <button
              type="button"
              className={[
                'flex-1 px-3 py-2 text-sm',
                tab === 'settings'
                  ? 'border-b-2 border-blue-500 text-blue-300'
                  : 'text-slate-400 hover:text-slate-200',
              ].join(' ')}
              onClick={() => setTab('settings')}
            >
              设置
            </button>
          </div>

          <div className="flex-1 overflow-auto p-3">
            {tab === 'current' ? (
              selectedLayer ? (
                <div className="grid gap-2 text-sm text-slate-200">
                  <div className="text-xs uppercase tracking-wide text-slate-400">
                    选中图层
                  </div>
                  <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                    <span className="font-medium text-white">{selectedLayer.id}</span>
                    <span className="text-xs text-slate-400">{selectedLayer.type}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                      <div className="text-xs text-slate-400">可见</div>
                      <div className="text-sm text-white">
                        {selectedLayer.visible ? '是' : '否'}
                      </div>
                    </div>
                    <div className="rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                      <div className="text-xs text-slate-400">透明度</div>
                      <div className="text-sm text-white">
                        {Math.round(selectedLayer.opacity * 100)}%
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <EventListPanel />
              )
            ) : tab === 'forecast' ? (
              <div className="grid gap-3 text-sm text-slate-200">
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  ECMWF 预报
                </div>
                <div className="grid gap-2 rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                  <div className="text-xs text-slate-400">起报时次</div>
                  <div className="text-sm text-white">{runTimeKey || '--'}</div>
                </div>

                <label className="grid gap-2 rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                  <span className="text-xs text-slate-400">高度层</span>
                  <select
                    className="w-full rounded-md border border-slate-400/20 bg-slate-900/40 px-2 py-1 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 disabled:cursor-not-allowed disabled:opacity-60"
                    value={levelKey}
                    onChange={(event) => setLevelKey(event.target.value)}
                    disabled={forecastStatus === 'loading' || forecastLevels.length === 0}
                  >
                    {forecastLevels.map((level) => (
                      <option key={level} value={level}>
                        {level}
                      </option>
                    ))}
                  </select>
                  <div className="text-xs text-slate-500">
                    温度/风矢图层将使用该高度层。
                  </div>
                </label>

                {forecastStatus === 'loading' ? (
                  <div className="text-xs text-slate-400">加载中…</div>
                ) : forecastStatus === 'error' ? (
                  <div className="text-xs text-red-300">{forecastError ?? '加载失败'}</div>
                ) : null}
              </div>
            ) : tab === 'settings' ? (
              <div className="grid gap-3 text-sm text-slate-200">
                <div className="text-xs uppercase tracking-wide text-slate-400">
                  渲染设置
                </div>
                <div className="grid gap-2 rounded-lg border border-slate-400/10 bg-slate-900/20 px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <PerformanceModeToggle />
                    <div className="text-xs text-slate-400">
                      FPS: {fps != null ? `${fps}` : 'N/A'}
                    </div>
                  </div>
                  <RealLightingToggle />
                  <OsmBuildingsToggle />
                  <div className="text-xs text-slate-400">
                    真实光照默认开启，开启后会增加渲染开销；如出现卡顿可随时关闭。Low 模式会减少粒子与风矢密度，并自动禁用真实光照/体云/建筑（如有），以提升低性能设备体验。
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-slate-400">该视图尚未实现。</div>
            )}
          </div>
        </div>
      </CollapsiblePanel>
    </aside>
  );
}
