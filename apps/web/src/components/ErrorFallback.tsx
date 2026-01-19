import { toUserFacingError } from '../lib/userFacingError';

type Props = {
  error: unknown;
  onRetry: () => void;
};

export default function ErrorFallback({ error, onRetry }: Props) {
  const { title, message } = toUserFacingError(error);

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-xl items-center px-6">
        <div className="w-full rounded-2xl border border-slate-400/20 bg-slate-900/60 p-6 shadow-lg">
          <div className="text-base font-semibold">{title}</div>
          <div className="mt-2 text-sm text-slate-300">{message}</div>
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
              onClick={onRetry}
            >
              重试
            </button>
            <button
              type="button"
              className="rounded-lg border border-slate-400/30 px-4 py-2 text-sm text-slate-100 hover:bg-slate-800/40"
              onClick={() => window.location.reload()}
            >
              刷新页面
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

