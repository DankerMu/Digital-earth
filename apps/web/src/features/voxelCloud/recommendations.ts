export type VoxelCloudRecommendedParams = {
  stepVoxels: number;
  stepMeters: number | null;
  maxSteps: number;
};

export type VoxelCloudRecommendInputs = {
  volumeShape: [number, number, number];
  dimensionsMeters?: { width: number; height: number; depth: number } | null;
  targetMaxSteps?: number;
};

function clamp(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function roundTo(value: number, step: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(step) || step <= 0) return value;
  return Math.round(value / step) * step;
}

function safeDim(value: number): number | null {
  if (!Number.isFinite(value) || value <= 0) return null;
  return value;
}

export function recommendVoxelCloudParams(inputs: VoxelCloudRecommendInputs): VoxelCloudRecommendedParams {
  const maxSteps = Math.round(
    clamp(
      typeof inputs.targetMaxSteps === 'number' && Number.isFinite(inputs.targetMaxSteps)
        ? inputs.targetMaxSteps
        : 128,
      16,
      512,
    ),
  );

  const shape = inputs.volumeShape;
  const dims = inputs.dimensionsMeters ?? null;

  const widthMeters = safeDim(dims?.width ?? NaN);
  const heightMeters = safeDim(dims?.height ?? NaN);
  const depthMeters = safeDim(dims?.depth ?? NaN);
  if (widthMeters == null || heightMeters == null || depthMeters == null) {
    return { stepVoxels: 1, stepMeters: null, maxSteps };
  }

  const voxelSizeX = widthMeters / shape[2];
  const voxelSizeY = heightMeters / shape[1];
  const voxelSizeZ = depthMeters / shape[0];
  const baseStepMeters = Math.min(voxelSizeX, voxelSizeY, voxelSizeZ);

  const diagonalMeters = Math.hypot(widthMeters, heightMeters, depthMeters);
  const requiredStepVoxels = diagonalMeters / (baseStepMeters * maxSteps);

  const stepVoxels = clamp(roundTo(Math.max(1, requiredStepVoxels), 0.25), 0.5, 4);
  const stepMeters = stepVoxels * baseStepMeters;

  return { stepVoxels, stepMeters, maxSteps };
}

