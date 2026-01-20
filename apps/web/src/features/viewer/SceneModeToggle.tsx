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
    <div className="sceneModePanel">
      <div className="sceneModeLabel">模式</div>
      <div className="sceneModeGroup" role="group" aria-label="视图模式">
        {MODE_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className="sceneModeButton"
            aria-pressed={option.id === sceneModeId}
            data-active={option.id === sceneModeId ? 'true' : 'false'}
            onClick={() => setSceneModeId(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

