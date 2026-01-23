import { BASEMAPS, getBasemapById, isBasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';

type BasemapSelectorProps = {
  ionEnabled: boolean;
};

export function BasemapSelector({ ionEnabled }: BasemapSelectorProps) {
  const basemapId = useBasemapStore((state) => state.basemapId);
  const setBasemapId = useBasemapStore((state) => state.setBasemapId);
  const basemap = getBasemapById(basemapId);
  const descriptionId = basemap?.description ? 'basemap-select-description' : undefined;

  return (
    <div className="basemapPanel">
      <label htmlFor="basemap-select" className="basemapLabel">
        底图
      </label>
      <select
        id="basemap-select"
        className="basemapSelect"
        aria-describedby={descriptionId}
        value={basemapId}
        onChange={(event) => {
          const next = event.target.value;
          if (isBasemapId(next)) setBasemapId(next);
        }}
      >
        {BASEMAPS.map((option) => (
          <option
            key={option.id}
            value={option.id}
            disabled={option.kind === 'ion' && !ionEnabled}
          >
            {option.label}
          </option>
        ))}
      </select>
      {basemap?.description ? (
        <div id="basemap-select-description" className="basemapHelp">
          {basemap.description}
        </div>
      ) : null}
    </div>
  );
}
