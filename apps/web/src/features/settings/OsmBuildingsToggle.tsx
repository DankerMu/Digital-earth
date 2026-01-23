import { useId } from 'react';
import { usePerformanceModeStore } from '../../state/performanceMode';
import { useOsmBuildingsStore } from '../../state/osmBuildings';

export default function OsmBuildingsToggle() {
  const performanceMode = usePerformanceModeStore((state) => state.mode);
  const lowModeEnabled = performanceMode === 'low';

  const enabled = useOsmBuildingsStore((state) => state.enabled);
  const setEnabled = useOsmBuildingsStore((state) => state.setEnabled);

  const effectiveEnabled = enabled && !lowModeEnabled;
  const inputId = useId();
  const statusId = useId();

  return (
    <div className="flex items-center gap-3 text-sm text-slate-300">
      <label htmlFor={inputId} className="min-w-12 text-slate-300">
        3D 建筑
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
          {lowModeEnabled ? 'Low 模式已关闭' : '开启'}
        </span>
      </div>
    </div>
  );
}
