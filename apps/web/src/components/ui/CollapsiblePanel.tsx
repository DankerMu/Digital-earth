import type { ReactNode } from 'react';

import { GlassPanel } from './GlassPanel';

export type CollapsiblePanelProps = {
  title: string;
  description?: ReactNode;
  collapsed: boolean;
  onToggleCollapsed: () => void;
  children: ReactNode;
  className?: string;
  headerClassName?: string;
  contentClassName?: string;
  actions?: ReactNode;
  collapsedLabel?: string;
  expandedLabel?: string;
  toggleIcons?: {
    collapsed: ReactNode;
    expanded: ReactNode;
  };
};

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function CollapsiblePanel({
  title,
  description,
  collapsed,
  onToggleCollapsed,
  children,
  className,
  headerClassName,
  contentClassName,
  actions,
  collapsedLabel,
  expandedLabel,
  toggleIcons,
}: CollapsiblePanelProps) {
  const toggleLabel = collapsed
    ? collapsedLabel ?? `展开${title}`
    : expandedLabel ?? `折叠${title}`;

  return (
    <GlassPanel className={cx('flex flex-col overflow-hidden', className)}>
      <header
        className={cx(
          'flex items-center justify-between gap-3 border-b border-slate-400/10 px-3 py-2',
          headerClassName,
        )}
      >
        <div className={collapsed ? 'sr-only' : 'min-w-0'}>
          <div className="truncate text-sm font-semibold text-white">{title}</div>
          {description ? <div className="text-xs text-slate-400">{description}</div> : null}
        </div>

        <div className="flex items-center gap-2">
          {actions}
          <button
            type="button"
            className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
            aria-label={toggleLabel}
            onClick={onToggleCollapsed}
          >
            {collapsed ? (toggleIcons?.collapsed ?? '▶') : (toggleIcons?.expanded ?? '◀')}
          </button>
        </div>
      </header>

      {collapsed ? null : (
        <div className={cx('flex-1 overflow-auto p-3', contentClassName)}>{children}</div>
      )}
    </GlassPanel>
  );
}
