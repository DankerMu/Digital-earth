import { useSceneModeStore, type SceneModeId } from '../../state/sceneMode';

const MODE_OPTIONS: Array<{ id: SceneModeId; label: string }> = [
  { id: '3d', label: '3D' },
  { id: '2d', label: '2D' },
  { id: 'columbus', label: '2.5D' },
];

export function SceneModeToggle() {
  const sceneModeId = useSceneModeStore((state) => state.sceneModeId);
  const setSceneModeId = useSceneModeStore((state) => state.setSceneModeId);

  return (
    <div className="grid gap-2">
      <div className="text-xs font-semibold tracking-wide text-slate-200">模式</div>
      <div className="flex gap-2" role="group" aria-label="视图模式">
        {MODE_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={[
              'flex-1 rounded-lg border px-3 py-2 text-xs font-semibold transition-colors',
              'focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400',
              option.id === sceneModeId
                ? 'border-blue-500/50 bg-blue-500/15 text-blue-200'
                : 'border-slate-400/20 bg-slate-900/30 text-slate-200 hover:bg-slate-700/40',
            ].join(' ')}
            aria-pressed={option.id === sceneModeId}
            onClick={() => setSceneModeId(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
