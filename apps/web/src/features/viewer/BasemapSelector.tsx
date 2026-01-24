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
    <div className="grid gap-2">
      <label htmlFor="basemap-select" className="text-xs font-semibold tracking-wide text-slate-200">
        底图
      </label>
      <select
        id="basemap-select"
        className="w-full rounded-lg border border-slate-400/20 bg-slate-900/40 px-3 py-2 text-sm text-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
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
        <div id="basemap-select-description" className="text-xs leading-snug text-slate-400">
          {basemap.description}
        </div>
      ) : null}
    </div>
  );
}
