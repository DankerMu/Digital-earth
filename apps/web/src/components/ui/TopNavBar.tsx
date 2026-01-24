export type TopNavBarProps = {
  className?: string;
  onOpenHelp?: () => void;
  onOpenSettings?: () => void;
};

function cx(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ');
}

export function TopNavBar({ className, onOpenHelp, onOpenSettings }: TopNavBarProps) {
  return (
    <nav
      className={cx(
        'fixed top-4 left-4 right-4 h-14 z-50',
        'bg-slate-800/80 backdrop-blur-xl border border-slate-400/20 rounded-xl shadow-lg',
        'hover:border-slate-400/40 transition-all duration-200',
        'flex items-center justify-between px-4',
        className,
      )}
      aria-label="Top navigation"
    >
      <div className="flex items-center gap-3">
        <svg
          className="h-8 w-8 text-blue-500"
          viewBox="0 0 24 24"
          fill="none"
          role="img"
          aria-label="Digital Earth"
        >
          <path
            d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z"
            stroke="currentColor"
            strokeWidth="1.8"
          />
          <path
            d="M2 12h20"
            stroke="currentColor"
            strokeWidth="1.2"
            opacity="0.7"
          />
          <path
            d="M12 2c3 2.5 4.5 6 4.5 10S15 19.5 12 22c-3-2.5-4.5-6-4.5-10S9 4.5 12 2Z"
            stroke="currentColor"
            strokeWidth="1.2"
            opacity="0.7"
          />
        </svg>
        <span className="text-sm font-semibold text-white">Digital Earth</span>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          className="rounded-lg p-2 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          aria-label="设置"
          onClick={onOpenSettings}
        >
          <svg className="h-5 w-5 text-slate-300" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z"
              stroke="currentColor"
              strokeWidth="1.8"
            />
            <path
              d="M19.4 15a7.98 7.98 0 0 0 .1-2 7.98 7.98 0 0 0-.1-2l2-1.5-2-3.4-2.3 1a8.1 8.1 0 0 0-3.5-2l-.3-2.5H10l-.3 2.5a8.1 8.1 0 0 0-3.5 2l-2.3-1-2 3.4 2 1.5a7.98 7.98 0 0 0-.1 2c0 .7 0 1.3.1 2l-2 1.5 2 3.4 2.3-1a8.1 8.1 0 0 0 3.5 2l.3 2.5h4.1l.3-2.5a8.1 8.1 0 0 0 3.5-2l2.3 1 2-3.4-2-1.5Z"
              stroke="currentColor"
              strokeWidth="1.2"
              opacity="0.75"
            />
          </svg>
        </button>

        <button
          type="button"
          className="rounded-lg p-2 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
          aria-label="帮助"
          onClick={onOpenHelp}
        >
          <svg className="h-5 w-5 text-slate-300" viewBox="0 0 24 24" fill="none">
            <path
              d="M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20Z"
              stroke="currentColor"
              strokeWidth="1.8"
            />
            <path
              d="M9.3 9a3 3 0 0 1 5.4 1.5c0 2-2 2.5-2 3.9v.6"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
            />
            <path
              d="M12 17.2h.01"
              stroke="currentColor"
              strokeWidth="3"
              strokeLinecap="round"
            />
          </svg>
        </button>
      </div>
    </nav>
  );
}

