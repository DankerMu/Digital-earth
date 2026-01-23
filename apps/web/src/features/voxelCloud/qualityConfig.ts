export type VoxelCloudQuality = 'low' | 'medium' | 'high';

export interface QualityPreset {
  // Grid resolution in meters
  res: number;
  // Ray march step count
  raySteps: number;
  // Min ms between API calls
  updateInterval: number;
}

export const QUALITY_PRESETS = {
  low: { res: 4000, raySteps: 32, updateInterval: 2000 },
  medium: { res: 2000, raySteps: 64, updateInterval: 1000 },
  high: { res: 1000, raySteps: 128, updateInterval: 500 },
} as const satisfies Record<VoxelCloudQuality, QualityPreset>;

