import type { POIRiskResult, RiskPOI } from './riskTypes';
import { formatRiskLevel, riskSeverityForLevel } from './riskTypes';

function formatNumber(value: number | null | undefined, digits: number): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(digits);
}

function severityLabel(level: number | null | undefined): string {
  const severity = riskSeverityForLevel(level);
  if (severity === 'high') return '高';
  if (severity === 'medium') return '中';
  if (severity === 'low') return '低';
  return '未知';
}

function severityClass(level: number | null | undefined): string {
  const severity = riskSeverityForLevel(level);
  if (severity === 'high') return 'border-red-500/40 bg-red-500/10 text-red-100';
  if (severity === 'medium') return 'border-orange-500/40 bg-orange-500/10 text-orange-100';
  if (severity === 'low') return 'border-yellow-500/40 bg-yellow-500/10 text-yellow-50';
  return 'border-slate-400/30 bg-slate-500/10 text-slate-100';
}

export type RiskPoiPopupProps = {
  poi: RiskPOI | null;
  evaluation: POIRiskResult | null;
  status: 'loading' | 'loaded' | 'error';
  errorMessage: string | null;
  onClose: () => void;
  onOpenDisasterDemo: () => void;
};

export function RiskPoiPopup({
  poi,
  evaluation,
  status,
  errorMessage,
  onClose,
  onOpenDisasterDemo,
}: RiskPoiPopupProps) {
  if (!poi) return null;

  const level = evaluation?.level ?? poi.risk_level;
  const reasons = [...(evaluation?.reasons ?? [])].sort(
    (a, b) => b.contribution - a.contribution,
  );
  const factors = [...(evaluation?.factors ?? [])].sort(
    (a, b) => b.contribution - a.contribution,
  );

  return (
    <aside
      aria-label="Risk POI details"
      data-testid="risk-poi-popup"
      className="w-96 max-w-[calc(100vw-24px)] rounded-xl border border-slate-400/20 bg-slate-900/70 p-4 text-slate-100 shadow-lg backdrop-blur-xl"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <div className="truncate text-sm font-semibold text-white">
              {poi.name}
            </div>
            <span
              className={[
                'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs',
                severityClass(level),
              ].join(' ')}
            >
              {severityLabel(level)}风险 · L{formatRiskLevel(level)}
            </span>
          </div>
          <div className="mt-1 text-xs text-slate-400">
            {poi.type} · {poi.lat.toFixed(4)}, {poi.lon.toFixed(4)}
          </div>
        </div>

        <button
          type="button"
          aria-label="Close risk popup"
          data-testid="risk-popup-close"
          className="rounded-lg border border-slate-400/20 bg-slate-800/40 px-2 py-1 text-xs text-slate-200 hover:bg-slate-800/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          onClick={onClose}
        >
          ✕
        </button>
      </header>

      <div className="mt-3 flex items-center justify-between gap-2">
        <div className="text-xs text-slate-400">风险详情</div>
        <button
          type="button"
          data-testid="risk-open-disaster-demo"
          className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-xs text-blue-100 hover:bg-blue-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          onClick={onOpenDisasterDemo}
        >
          查看灾害演示
        </button>
      </div>

      {status === 'loading' ? (
        <div className="mt-3 text-sm text-slate-300" aria-label="Risk details loading">
          加载中…
        </div>
      ) : null}

      {status === 'error' ? (
        <div className="mt-3 text-sm text-red-300" role="alert" aria-label="Risk details error">
          {errorMessage || '加载失败'}
        </div>
      ) : null}

      {status === 'loaded' ? (
        <div className="mt-3 grid gap-4">
          <section>
            <div className="text-xs uppercase tracking-wide text-slate-400">Reasons</div>
            {reasons.length === 0 ? (
              <div className="mt-2 text-sm text-slate-300">暂无 reasons</div>
            ) : (
              <div className="mt-2 overflow-hidden rounded-lg border border-slate-400/10">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-800/40 text-xs text-slate-300">
                    <tr>
                      <th className="px-3 py-2">因子</th>
                      <th className="px-3 py-2 text-right">当前值</th>
                      <th className="px-3 py-2 text-right">阈值</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reasons.map((reason) => (
                      <tr key={`${reason.factor_id}:${reason.threshold}`} className="border-t border-slate-400/10">
                        <td className="px-3 py-2 text-slate-100">{reason.factor_name}</td>
                        <td className="px-3 py-2 text-right font-medium text-slate-100">
                          {formatNumber(reason.value, 2)}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-200">
                          {formatNumber(reason.threshold, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section>
            <div className="text-xs uppercase tracking-wide text-slate-400">Factors</div>
            {factors.length === 0 ? (
              <div className="mt-2 text-sm text-slate-300">暂无因子信息</div>
            ) : (
              <div className="mt-2 overflow-hidden rounded-lg border border-slate-400/10">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-800/40 text-xs text-slate-300">
                    <tr>
                      <th className="px-3 py-2">因子</th>
                      <th className="px-3 py-2 text-right">值</th>
                      <th className="px-3 py-2 text-right">贡献</th>
                    </tr>
                  </thead>
                  <tbody>
                    {factors.map((factor) => (
                      <tr key={factor.id} className="border-t border-slate-400/10">
                        <td className="px-3 py-2 text-slate-100">{factor.id}</td>
                        <td className="px-3 py-2 text-right font-medium text-slate-100">
                          {formatNumber(factor.value, 2)}
                        </td>
                        <td className="px-3 py-2 text-right text-slate-200">
                          {formatNumber(factor.contribution, 3)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      ) : null}
    </aside>
  );
}
