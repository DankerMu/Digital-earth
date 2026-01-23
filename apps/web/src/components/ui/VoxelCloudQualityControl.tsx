import type { ChangeEvent } from 'react';

import { usePerformanceModeStore } from '../../state/performanceMode';
import type { VoxelCloudQuality } from '../../features/voxelCloud/qualityConfig';

export type VoxelCloudQualityControlProps = {
  className?: string;
};

function isVoxelCloudQuality(value: string): value is VoxelCloudQuality {
  return value === 'low' || value === 'medium' || value === 'high';
}

export function VoxelCloudQualityControl(props: VoxelCloudQualityControlProps = {}) {
  const quality = usePerformanceModeStore((state) => state.voxelCloudQuality);
  const autoDowngrade = usePerformanceModeStore((state) => state.autoDowngrade);
  const setVoxelCloudQuality = usePerformanceModeStore((state) => state.setVoxelCloudQuality);
  const setAutoDowngrade = usePerformanceModeStore((state) => state.setAutoDowngrade);

  const onQualityChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    if (!isVoxelCloudQuality(value)) return;
    setVoxelCloudQuality(value);
  };

  return (
    <div className={props.className}>
      <label className="block">
        <div className="mb-1 text-slate-300">Voxel cloud quality</div>
        <select
          className="w-full rounded-md border border-slate-400/20 bg-slate-900/50 px-2 py-1 text-slate-100"
          value={quality}
          onChange={onQualityChange}
        >
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
        </select>
      </label>

      <label className="mt-2 flex items-center gap-2 text-xs text-slate-100">
        <input
          type="checkbox"
          checked={autoDowngrade}
          onChange={(event) => setAutoDowngrade(event.target.checked)}
        />
        Auto-downgrade (FPS)
      </label>
    </div>
  );
}
