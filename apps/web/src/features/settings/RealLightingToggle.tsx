import { useId } from 'react';

import { usePerformanceModeStore } from '../../state/performanceMode';
import { useRealLightingStore } from '../../state/realLighting';

export default function RealLightingToggle() {
  const performanceMode = usePerformanceModeStore((state) => state.mode);
  const lowModeEnabled = performanceMode === 'low';

  const enabled = useRealLightingStore((state) => state.enabled);
  const setEnabled = useRealLightingStore((state) => state.setEnabled);

  const effectiveEnabled = enabled && !lowModeEnabled;
  const inputId = useId();
  const statusId = useId();

  const statusLabel = lowModeEnabled ? 'Low 模式下禁用' : effectiveEnabled ? '开启' : '关闭';

  return (
    <div className="flex items-center gap-3 text-sm text-slate-300">
      <label htmlFor={inputId} className="min-w-24 text-slate-300">
        真实光照（性能开销）
      </label>
      <div className="flex items-center gap-2">
        <input
          id={inputId}
          type="checkbox"
          className="h-4 w-4 accent-blue-500"
          checked={effectiveEnabled}
          disabled={lowModeEnabled}
          aria-describedby={statusId}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span id={statusId} className={lowModeEnabled ? 'text-slate-500' : undefined}>
          {statusLabel}
        </span>
      </div>
    </div>
  );
}
