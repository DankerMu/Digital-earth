import { usePerformanceModeStore } from '../../state/performanceMode';
import { useOsmBuildingsStore } from '../../state/osmBuildings';

export default function OsmBuildingsToggle() {
  const performanceMode = usePerformanceModeStore((state) => state.mode);
  const lowModeEnabled = performanceMode === 'low';

  const enabled = useOsmBuildingsStore((state) => state.enabled);
  const setEnabled = useOsmBuildingsStore((state) => state.setEnabled);

  const effectiveEnabled = enabled && !lowModeEnabled;

  return (
    <div className="flex items-center gap-3 text-sm text-slate-300" role="group" aria-label="3D 建筑">
      <span className="min-w-12 text-slate-300">3D 建筑</span>
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          className="h-4 w-4 accent-blue-500"
          checked={effectiveEnabled}
          disabled={lowModeEnabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span className={lowModeEnabled ? 'text-slate-500' : undefined}>
          {lowModeEnabled ? 'Low 模式已关闭' : '开启'}
        </span>
      </label>
    </div>
  );
}

