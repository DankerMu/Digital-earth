import type { ReactNode } from 'react';

import { toUserFacingError } from '../lib/userFacingError';

type Props = {
  error: unknown;
  action?: ReactNode;
};

export default function HttpErrorNotice({ error, action }: Props) {
  const { title, message, status } = toUserFacingError(error);

  return (
    <div
      className="rounded-xl border border-slate-400/20 bg-slate-900/60 p-4"
      role="alert"
      aria-label={`error-${status ?? 'unknown'}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-slate-100">{title}</div>
          <div className="mt-1 text-sm text-slate-300">{message}</div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    </div>
  );
}

