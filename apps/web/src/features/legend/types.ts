export type LayerType = 'temperature' | 'cloud' | 'precipitation' | 'wind';

export const SUPPORTED_LAYER_TYPES: LayerType[] = [
  'temperature',
  'cloud',
  'precipitation',
  'wind',
];

export type LegendConfig = {
  colors: string[];
  thresholds: number[];
  labels: string[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function parseLegendConfig(value: unknown): LegendConfig {
  if (!isRecord(value)) {
    throw new Error('Legend config must be an object');
  }

  const { colors, thresholds, labels } = value;

  if (!Array.isArray(colors) || colors.length === 0) {
    throw new Error('Legend config.colors must be a non-empty array');
  }
  if (!Array.isArray(thresholds) || thresholds.length === 0) {
    throw new Error('Legend config.thresholds must be a non-empty array');
  }
  if (!Array.isArray(labels) || labels.length === 0) {
    throw new Error('Legend config.labels must be a non-empty array');
  }
  if (colors.length !== thresholds.length || colors.length !== labels.length) {
    throw new Error('Legend config arrays must have equal lengths');
  }

  const parsedThresholds = thresholds.map((item) => {
    const num = typeof item === 'number' ? item : Number(item);
    if (!Number.isFinite(num)) {
      throw new Error('Legend config.thresholds must be numbers');
    }
    return num;
  });

  return {
    colors: colors.map((item) => String(item)),
    thresholds: parsedThresholds,
    labels: labels.map((item) => String(item)),
  };
}

