import { useMemo } from 'react';

import { useViewModeStore } from '../../state/viewMode';
import { useProductsPanel } from './useProductsPanel';
import type { ProductHazardSummary, ProductSummary } from './productsTypes';

type SeverityStyle = { label: string; className: string };

const SEVERITY_ORDER = new Map<string, number>([
  ['low', 1],
  ['medium', 2],
  ['high', 3],
]);

function pickTopSeverity(hazards: ProductHazardSummary[]): string | null {
  if (hazards.length === 0) return null;
  return (
    hazards
      .map((hazard) => hazard.severity)
      .sort((a, b) => (SEVERITY_ORDER.get(b) ?? 0) - (SEVERITY_ORDER.get(a) ?? 0))[0] ?? null
  );
}

function severityStyle(value: string | null): SeverityStyle {
  if (!value) return { label: '未知', className: 'bg-slate-500/20 text-slate-200' };

  const normalized = value.trim().toLowerCase();

  if (normalized === 'low') return { label: '低', className: 'bg-emerald-500/20 text-emerald-200' };
  if (normalized === 'medium') return { label: '中', className: 'bg-amber-500/20 text-amber-200' };
  if (normalized === 'high') return { label: '高', className: 'bg-rose-500/20 text-rose-200' };

  return { label: value, className: 'bg-slate-500/20 text-slate-200' };
}

function formatUtcMinute(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const normalized = date.toISOString();
  return `${normalized.slice(0, 16).replace('T', ' ')}Z`;
}

function productTitle(product: ProductSummary, detailText: string | null | undefined): string {
  const preferred = detailText?.trim() ?? '';
  if (preferred) return preferred;
  return product.title;
}

export function EventListPanel() {
  const route = useViewModeStore((state) => state.route);
  const enterEvent = useViewModeStore((state) => state.enterEvent);

  const selectedProductId = route.viewModeId === 'event' ? route.productId : null;

  const { list, items, detailsById, detailsStatus, reload } = useProductsPanel();

  const rows = useMemo(() => {
    return items.map((product) => {
      const id = String(product.id);
      const detail = detailsById[id];
      const severity = pickTopSeverity(product.hazards);
      return {
        id,
        type: product.title,
        title: productTitle(product, detail?.text),
        severity,
        validFrom: detail?.valid_from ?? null,
        validTo: detail?.valid_to ?? null,
      };
    });
  }, [detailsById, items]);

  return (
    <section aria-label="事件列表" className="grid gap-3">
      <header className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs uppercase tracking-wide text-slate-400">Products</div>
          <div className="truncate text-sm font-semibold text-white">事件列表</div>
        </div>

        <button
          type="button"
          className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          onClick={reload}
        >
          刷新
        </button>
      </header>

      {list.status === 'loading' ? (
        <div className="text-sm text-slate-400">Loading…</div>
      ) : list.status === 'error' ? (
        <div className="rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
          {list.message}
        </div>
      ) : rows.length === 0 ? (
        <div className="text-sm text-slate-400">暂无事件</div>
      ) : (
        <div
          className="grid gap-2"
          role="listbox"
          aria-label="事件列表"
          aria-busy={detailsStatus === 'loading'}
        >
          {rows.map((row) => {
            const selected = selectedProductId === row.id;
            const level = severityStyle(row.severity);
            const validText =
              row.validFrom && row.validTo
                ? `${formatUtcMinute(row.validFrom)} ~ ${formatUtcMinute(row.validTo)}`
                : detailsStatus === 'loading'
                  ? '加载中…'
                  : '—';

            return (
              <button
                key={row.id}
                type="button"
                role="option"
                aria-selected={selected}
                data-selected={selected ? 'true' : 'false'}
                data-testid={`event-item-${row.id}`}
                className={[
                  'w-full rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400',
                  selected
                    ? 'border-blue-400/60 bg-blue-500/15'
                    : 'border-slate-400/10 bg-slate-900/20 hover:bg-slate-900/30',
                ].join(' ')}
                onClick={() => enterEvent({ productId: row.id })}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-white">{row.title}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                      <span className="rounded-md border border-slate-400/10 bg-slate-950/20 px-2 py-0.5">
                        类型: {row.type}
                      </span>
                      <span className={['rounded-md px-2 py-0.5', level.className].join(' ')}>
                        等级: {level.label}
                      </span>
                    </div>
                    <div className="mt-1 text-xs text-slate-400">有效期: {validText}</div>
                  </div>
                  <div className="shrink-0 text-xs text-slate-500">#{row.id}</div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </section>
  );
}

