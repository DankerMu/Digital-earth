import { describe, expect, it } from 'vitest';

import { QUALITY_PRESETS, type QualityPreset, type VoxelCloudQuality } from './qualityConfig';

describe('qualityConfig', () => {
  it('exposes the expected preset keys', () => {
    const keys = Object.keys(QUALITY_PRESETS).sort();
    expect(keys).toEqual(['high', 'low', 'medium']);
  });

  it('matches the documented preset values', () => {
    expect(QUALITY_PRESETS.low).toEqual({ res: 4000, raySteps: 32, updateInterval: 2000 });
    expect(QUALITY_PRESETS.medium).toEqual({ res: 2000, raySteps: 64, updateInterval: 1000 });
    expect(QUALITY_PRESETS.high).toEqual({ res: 1000, raySteps: 128, updateInterval: 500 });
  });
});

// Compile-time type safety checks.
const _typedPresets: Record<VoxelCloudQuality, QualityPreset> = QUALITY_PRESETS;
void _typedPresets;

