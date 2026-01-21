import type { SamplingCardState } from './useSamplingCard';

function formatLonLat(value: number): string {
  if (!Number.isFinite(value)) return '--';
  return value.toFixed(4);
}

function formatNumber(value: number | null, digits: number): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(digits);
}

function formatInteger(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return String(Math.round(value));
}

function formatWindDirection(value: number | null): string {
  if (value == null || !Number.isFinite(value)) return '--';
  const wrapped = ((value % 360) + 360) % 360;
  return `${Math.round(wrapped)}°`;
}

export type SamplingCardProps = {
  state: SamplingCardState;
  onClose: () => void;
};

export function SamplingCard({ state, onClose }: SamplingCardProps) {
  if (!state.isOpen || !state.location) return null;

  const { location, status, data, errorMessage } = state;

  return (
    <aside
      aria-label="Sampling data"
      className="w-80 max-w-[calc(100vw-24px)] rounded-xl border border-slate-400/20 bg-slate-900/60 p-4 text-slate-100 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-white">点取样</div>
          <div className="mt-1 text-xs text-slate-400">
            {formatLonLat(location.lat)}, {formatLonLat(location.lon)}
          </div>
        </div>

        <button
          type="button"
          aria-label="Close sampling card"
          className="rounded-lg border border-slate-400/20 bg-slate-800/40 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          onClick={onClose}
        >
          ✕
        </button>
      </header>

      {status === 'loading' ? (
        <div className="mt-3 text-sm text-slate-300" aria-label="Sampling loading">
          Sampling…
        </div>
      ) : null}

      {status === 'error' ? (
        <div className="mt-3 text-sm text-red-300" role="alert" aria-label="Sampling error">
          {errorMessage || 'Sampling failed'}
        </div>
      ) : null}

      {status === 'loaded' && data ? (
        <dl className="mt-3 grid grid-cols-[1fr_auto] gap-x-3 gap-y-2 text-sm">
          <dt className="text-slate-300">温度</dt>
          <dd className="text-right font-medium text-white">
            {formatNumber(data.temperatureC, 1)} <span className="text-slate-400">°C</span>
          </dd>

          <dt className="text-slate-300">风速 / 风向</dt>
          <dd className="text-right font-medium text-white">
            {formatNumber(data.windSpeedMps, 1)} <span className="text-slate-400">m/s</span>
            <span className="text-slate-500"> · </span>
            {formatWindDirection(data.windDirectionDeg)}
          </dd>

          <dt className="text-slate-300">降水</dt>
          <dd className="text-right font-medium text-white">
            {formatNumber(data.precipitationMm, 1)} <span className="text-slate-400">mm</span>
          </dd>

          <dt className="text-slate-300">云量</dt>
          <dd className="text-right font-medium text-white">
            {formatInteger(data.cloudCoverPercent)} <span className="text-slate-400">%</span>
          </dd>
        </dl>
      ) : null}
    </aside>
  );
}

