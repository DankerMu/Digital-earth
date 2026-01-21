import type { LayerConfig } from '../../state/layerManager';

function formatLonLat(value: number): string {
  if (!Number.isFinite(value)) return '--';
  return value.toFixed(4);
}

function formatHeightMeters(value: number | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return String(Math.round(value));
}

function formatActiveLayer(layer: LayerConfig | null): string {
  if (!layer) return '--';
  const variable = layer.variable.trim();
  const base = variable ? `${layer.type}:${variable}` : layer.type;
  if (layer.level == null || !Number.isFinite(layer.level)) return base;
  return `${base} · L${Math.round(layer.level)}`;
}

export type LocalInfoPanelProps = {
  lat: number;
  lon: number;
  heightMeters?: number;
  timeKey: string | null;
  activeLayer: LayerConfig | null;
  canGoBack: boolean;
  onBack: () => void;
};

export function LocalInfoPanel({
  lat,
  lon,
  heightMeters,
  timeKey,
  activeLayer,
  canGoBack,
  onBack,
}: LocalInfoPanelProps) {
  return (
    <aside
      aria-label="Local info"
      className="w-80 max-w-[calc(100vw-24px)] rounded-xl border border-slate-400/20 bg-slate-900/60 p-4 text-slate-100 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-white">局地信息</div>
          <div className="mt-1 text-xs text-slate-400">
            {formatLonLat(lat)}, {formatLonLat(lon)}
          </div>
        </div>

        <button
          type="button"
          aria-label="Back to previous view"
          className="rounded-lg border border-slate-400/20 bg-slate-800/40 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800/60 disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          disabled={!canGoBack}
          onClick={onBack}
        >
          返回
        </button>
      </header>

      <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-sm">
        <dt className="text-slate-300">海拔</dt>
        <dd className="text-right font-medium text-white">
          {formatHeightMeters(heightMeters)} <span className="text-slate-400">m</span>
        </dd>

        <dt className="text-slate-300">时间</dt>
        <dd className="text-right font-medium text-white">{timeKey ?? '--'}</dd>

        <dt className="text-slate-300">图层</dt>
        <dd className="text-right font-medium text-white">
          {formatActiveLayer(activeLayer)}
        </dd>
      </dl>
    </aside>
  );
}

