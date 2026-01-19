import type { ReactNode } from 'react';

type Props = {
  isAvailable: boolean;
  message?: string;
  children: ReactNode;
};

export default function DataGuard({ isAvailable, message, children }: Props) {
  if (isAvailable) return <>{children}</>;

  return (
    <div className="relative" data-unavailable="true">
      <div className="pointer-events-none select-none opacity-40 grayscale">
        {children}
      </div>
      <div className="absolute inset-0 flex items-center justify-center p-3">
        <div className="rounded-lg border border-slate-400/20 bg-slate-950/70 px-3 py-2 text-sm text-slate-200">
          {message ?? '数据缺失，已降级展示。'}
        </div>
      </div>
    </div>
  );
}

