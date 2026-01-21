import type { LayerConfig } from '../../state/layerManager';
import { useCameraPerspectiveStore, type CameraPerspectiveId } from '../../state/cameraPerspective';

const PERSPECTIVE_LABELS: Record<CameraPerspectiveId, string> = {
  upward: '仰视',
  forward: '平视',
  free: '自由',
};

function PerspectiveIcon({ id }: { id: CameraPerspectiveId }) {
  if (id === 'upward') {
    return (
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
        <path
          d="M8 3l4 4H9v6H7V7H4l4-4z"
          fill="currentColor"
        />
      </svg>
    );
  }

  if (id === 'forward') {
    return (
      <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
        <path
          d="M3 8h8.2L9 5.8 10.2 4.6 14.6 9l-4.4 4.4L9 12.2 11.2 10H3V8z"
          fill="currentColor"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" aria-hidden="true">
      <path
        d="M8 2l2 2H9v3h3V6l2 2-2 2V9H9v3h1l-2 2-2-2h1V9H4v1L2 8l2-2v1h3V4H6l2-2z"
        fill="currentColor"
      />
    </svg>
  );
}

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
  const cameraPerspectiveId = useCameraPerspectiveStore((state) => state.cameraPerspectiveId);
  const setCameraPerspectiveId = useCameraPerspectiveStore((state) => state.setCameraPerspectiveId);

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

      <div className="mt-3 flex items-center justify-between gap-3">
        <div className="text-xs text-slate-400">相机视角</div>
        <div
          className="flex divide-x divide-slate-400/20 overflow-hidden rounded-lg border border-slate-400/20 bg-slate-800/40"
          role="group"
          aria-label="Camera perspective"
        >
          {(Object.keys(PERSPECTIVE_LABELS) as CameraPerspectiveId[]).map((id) => (
            <button
              key={id}
              type="button"
              className="flex items-center gap-1 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400 data-[active=true]:bg-slate-800/70 data-[active=true]:text-white"
              aria-pressed={id === cameraPerspectiveId}
              data-active={id === cameraPerspectiveId ? 'true' : 'false'}
              onClick={() => setCameraPerspectiveId(id)}
            >
              <PerspectiveIcon id={id} />
              <span>{PERSPECTIVE_LABELS[id]}</span>
            </button>
          ))}
        </div>
      </div>

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
