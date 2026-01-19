import { BASEMAPS, getBasemapById, isBasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';

export function BasemapSelector() {
  const basemapId = useBasemapStore((state) => state.basemapId);
  const setBasemapId = useBasemapStore((state) => state.setBasemapId);
  const basemap = getBasemapById(basemapId);

  return (
    <div className="basemapPanel">
      <label htmlFor="basemap-select" className="basemapLabel">
        底图
      </label>
      <select
        id="basemap-select"
        className="basemapSelect"
        value={basemapId}
        onChange={(event) => {
          const next = event.target.value;
          if (isBasemapId(next)) setBasemapId(next);
        }}
      >
        {BASEMAPS.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
      {basemap?.description ? (
        <div className="basemapHelp" aria-label="Basemap description">
          {basemap.description}
        </div>
      ) : null}
    </div>
  );
}

