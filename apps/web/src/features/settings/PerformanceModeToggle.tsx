import { usePerformanceModeStore } from '../../state/performanceMode';

export default function PerformanceModeToggle() {
  const enabled = usePerformanceModeStore((state) => state.enabled);
  const setEnabled = usePerformanceModeStore((state) => state.setEnabled);

  return (
    <label className="flex items-center gap-2 text-sm text-slate-300">
      <input
        type="checkbox"
        className="h-4 w-4 accent-blue-500"
        checked={enabled}
        onChange={(event) => setEnabled(event.target.checked)}
      />
      <span>性能模式</span>
    </label>
  );
}

