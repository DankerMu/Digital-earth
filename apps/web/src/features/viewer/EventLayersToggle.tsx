import { useEventLayersStore, type EventLayerMode } from '../../state/eventLayers';

const MODE_OPTIONS: Array<{ id: EventLayerMode; label: string }> = [
  { id: 'monitoring', label: '监测' },
  { id: 'history', label: '历史' },
  { id: 'difference', label: '差值' },
];

export function EventLayersToggle() {
  const enabled = useEventLayersStore((state) => state.enabled);
  const setEnabled = useEventLayersStore((state) => state.setEnabled);
  const mode = useEventLayersStore((state) => state.mode);
  const setMode = useEventLayersStore((state) => state.setMode);

  return (
    <div className="eventLayersPanel">
      <div className="eventLayersHeader">
        <div className="eventLayersLabel">事件图层</div>
        <label className="eventLayersSwitch">
          <span className="eventLayersSwitchText">显示</span>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
            aria-label="显示事件图层"
          />
        </label>
      </div>

      {enabled ? (
        <div className="eventLayersGroup" role="group" aria-label="事件图层切换">
          {MODE_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className="eventLayersButton"
              aria-pressed={option.id === mode}
              data-active={option.id === mode ? 'true' : 'false'}
              onClick={() => setMode(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : (
        <div className="eventLayersHelp">关闭后隐藏，避免信息过载。</div>
      )}
    </div>
  );
}
