import { useMemo, useState, type ReactNode } from 'react';

export type GlassPanelProps = {
  children: ReactNode;
  className?: string;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  title?: string;
};

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function GlassPanel({
  children,
  className,
  collapsible = false,
  defaultCollapsed = false,
  title,
}: GlassPanelProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const hasHeader = Boolean(title) || collapsible;
  const isCollapsed = collapsible ? collapsed : false;

  const toggleLabel = useMemo(() => {
    const base = title?.trim() ? `${title}面板` : '面板';
    return isCollapsed ? `展开${base}` : `折叠${base}`;
  }, [isCollapsed, title]);

  return (
    <section
      className={cx(
        'bg-slate-800/80 backdrop-blur-xl border border-slate-400/20 rounded-xl shadow-lg hover:border-slate-400/40 transition-all duration-200',
        hasHeader && 'flex flex-col overflow-hidden',
        className,
      )}
    >
      {hasHeader ? (
        <header className="flex items-center justify-between gap-3 border-b border-slate-400/10 px-4 py-3">
          <div className={isCollapsed ? 'sr-only' : 'min-w-0'}>
            {title ? (
              <div className="truncate text-sm font-semibold text-white">{title}</div>
            ) : null}
          </div>

          {collapsible ? (
            <button
              type="button"
              className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
              aria-label={toggleLabel}
              onClick={() => setCollapsed((prev) => !prev)}
            >
              {isCollapsed ? '▶' : '◀'}
            </button>
          ) : null}
        </header>
      ) : null}

      {isCollapsed ? null : children}
    </section>
  );
}

