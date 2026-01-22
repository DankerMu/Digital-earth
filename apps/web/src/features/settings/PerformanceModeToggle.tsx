import { usePerformanceModeStore } from '../../state/performanceMode';

export default function PerformanceModeToggle() {
  const mode = usePerformanceModeStore((state) => state.mode);
  const setMode = usePerformanceModeStore((state) => state.setMode);

  return (
    <div className="flex items-center gap-3 text-sm text-slate-300" role="radiogroup" aria-label="性能模式">
      <span className="min-w-12 text-slate-300">性能模式</span>
      <label className="flex items-center gap-2">
        <input
          type="radio"
          className="h-4 w-4 accent-blue-500"
          name="performance-mode"
          value="high"
          checked={mode === 'high'}
          onChange={() => setMode('high')}
        />
        <span>High</span>
      </label>
      <label className="flex items-center gap-2">
        <input
          type="radio"
          className="h-4 w-4 accent-blue-500"
          name="performance-mode"
          value="low"
          checked={mode === 'low'}
          onChange={() => setMode('low')}
        />
        <span>Low</span>
      </label>
    </div>
  );
}
