import { Cartesian3, Color, PolylineArrowMaterialProperty, type Viewer } from 'cesium';

export type WindVector = {
  lon: number;
  lat: number;
  u: number;
  v: number;
};

export type WindArrowsOptions = {
  maxArrows?: number;
  maxArrowsPerformance?: number;
  metersPerSecondToLength?: number;
  minArrowLengthMeters?: number;
  maxArrowLengthMeters?: number;
  widthPixels?: number;
};

export type WindArrowsUpdate = {
  enabled: boolean;
  opacity: number;
  vectors: WindVector[];
  lowModeEnabled: boolean;
};

const DEFAULT_MAX_ARROWS = 600;
const DEFAULT_METERS_PER_SECOND_TO_LENGTH = 2500;
const DEFAULT_MIN_ARROW_LENGTH_METERS = 2000;
const DEFAULT_MAX_ARROW_LENGTH_METERS = 80_000;
const DEFAULT_WIDTH_PIXELS = 2;

const METERS_PER_DEGREE_LAT = 111_320;
const MIN_METERS_PER_DEGREE_LON = 1;

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function clamp01(value: number): number {
  return clamp(value, 0, 1);
}

function normalizeWindArrowsUpdate(update: WindArrowsUpdate): WindArrowsUpdate {
  return {
    ...update,
    opacity: clamp01(update.opacity),
    vectors: Array.isArray(update.vectors) ? update.vectors : [],
  };
}

function windSpeedMetersPerSecond(u: number, v: number): number {
  if (!Number.isFinite(u) || !Number.isFinite(v)) return 0;
  return Math.sqrt(u * u + v * v);
}

function metersPerDegreeLonAtLatitude(latitudeDegrees: number): number {
  const radians = (latitudeDegrees * Math.PI) / 180;
  const meters = METERS_PER_DEGREE_LAT * Math.cos(radians);
  if (!Number.isFinite(meters)) return MIN_METERS_PER_DEGREE_LON;
  return Math.max(MIN_METERS_PER_DEGREE_LON, Math.abs(meters));
}

function wrapLongitudeDegrees(lon: number): number {
  if (!Number.isFinite(lon)) return 0;
  const wrapped = ((lon + 180) % 360 + 360) % 360 - 180;
  return wrapped;
}

function clampLatitudeDegrees(lat: number): number {
  return clamp(lat, -89.999, 89.999);
}

export function windArrowDensityForCameraHeight(options: {
  cameraHeightMeters: number | null;
  lowModeEnabled: boolean;
}): number {
  const height = options.cameraHeightMeters ?? Number.NaN;
  if (!Number.isFinite(height)) return options.lowModeEnabled ? 6 : 12;

  let density = 32;
  if (height > 20_000_000) density = 4;
  else if (height > 10_000_000) density = 6;
  else if (height > 5_000_000) density = 8;
  else if (height > 2_000_000) density = 12;
  else if (height > 1_000_000) density = 16;
  else if (height > 500_000) density = 20;
  else if (height > 200_000) density = 24;
  else if (height > 100_000) density = 28;

  if (options.lowModeEnabled) {
    density = Math.max(1, Math.floor(density / 2));
  }

  return density;
}

function downsampleVectors(vectors: WindVector[], maxCount: number): WindVector[] {
  if (vectors.length <= maxCount) return vectors;
  if (maxCount <= 0) return [];

  const sampled: WindVector[] = [];
  const step = vectors.length / maxCount;
  for (let i = 0; i < maxCount; i += 1) {
    const index = Math.min(vectors.length - 1, Math.floor(i * step));
    sampled.push(vectors[index]!);
  }
  return sampled;
}

function computeArrowEndpoints(vector: WindVector, arrowLengthMeters: number): {
  startLon: number;
  startLat: number;
  endLon: number;
  endLat: number;
} | null {
  const speed = windSpeedMetersPerSecond(vector.u, vector.v);
  if (speed <= 0 || !Number.isFinite(speed)) return null;

  const eastUnit = vector.u / speed;
  const northUnit = vector.v / speed;

  const eastMeters = eastUnit * arrowLengthMeters;
  const northMeters = northUnit * arrowLengthMeters;

  const metersPerLon = metersPerDegreeLonAtLatitude(vector.lat);
  const deltaLon = eastMeters / metersPerLon;
  const deltaLat = northMeters / METERS_PER_DEGREE_LAT;

  const startLon = wrapLongitudeDegrees(vector.lon);
  const startLat = clampLatitudeDegrees(vector.lat);
  const endLon = wrapLongitudeDegrees(startLon + deltaLon);
  const endLat = clampLatitudeDegrees(startLat + deltaLat);

  return { startLon, startLat, endLon, endLat };
}

export class WindArrows {
  private readonly viewer: Viewer;
  private readonly options: Required<WindArrowsOptions>;
  private entities: unknown[] = [];
  private current: WindArrowsUpdate = {
    enabled: false,
    opacity: 1,
    vectors: [],
    lowModeEnabled: false,
  };

  constructor(viewer: Viewer, options: WindArrowsOptions = {}) {
    this.viewer = viewer;
    const maxArrows = options.maxArrows ?? DEFAULT_MAX_ARROWS;
    this.options = {
      maxArrows,
      maxArrowsPerformance: options.maxArrowsPerformance ?? Math.floor(maxArrows * 0.5),
      metersPerSecondToLength:
        options.metersPerSecondToLength ?? DEFAULT_METERS_PER_SECOND_TO_LENGTH,
      minArrowLengthMeters: options.minArrowLengthMeters ?? DEFAULT_MIN_ARROW_LENGTH_METERS,
      maxArrowLengthMeters: options.maxArrowLengthMeters ?? DEFAULT_MAX_ARROW_LENGTH_METERS,
      widthPixels: options.widthPixels ?? DEFAULT_WIDTH_PIXELS,
    };
  }

  update(update: WindArrowsUpdate): void {
    this.current = normalizeWindArrowsUpdate(update);

    const maxArrows = this.current.lowModeEnabled
      ? this.options.maxArrowsPerformance
      : this.options.maxArrows;

    const shouldRender =
      this.current.enabled &&
      this.current.opacity > 0 &&
      maxArrows > 0 &&
      this.current.vectors.length > 0;

    if (!shouldRender) {
      this.clear();
      return;
    }

    const sampled = downsampleVectors(this.current.vectors, maxArrows);
    this.render(sampled, { opacity: this.current.opacity });
  }

  destroy(): void {
    this.clear();
  }

  private render(vectors: WindVector[], style: { opacity: number }): void {
    this.clear();

    const width = clamp(this.options.widthPixels, 1, 10);
    const color = Color.WHITE.withAlpha(style.opacity);
    const material = new PolylineArrowMaterialProperty(color);

    const entities = this.viewer.entities as unknown as {
      add: (entity: unknown) => unknown;
    };

    for (let index = 0; index < vectors.length; index += 1) {
      const vector = vectors[index]!;
      const speed = windSpeedMetersPerSecond(vector.u, vector.v);
      if (speed <= 0) continue;

      const arrowLengthMeters = clamp(
        speed * this.options.metersPerSecondToLength,
        this.options.minArrowLengthMeters,
        this.options.maxArrowLengthMeters,
      );

      const endpoints = computeArrowEndpoints(vector, arrowLengthMeters);
      if (!endpoints) continue;

      const start = Cartesian3.fromDegrees(endpoints.startLon, endpoints.startLat, 0);
      const end = Cartesian3.fromDegrees(endpoints.endLon, endpoints.endLat, 0);

      const entity = entities.add({
        id: `wind-arrow-${index}`,
        show: true,
        polyline: {
          positions: [start, end],
          width,
          material,
          clampToGround: true,
        },
      });

      this.entities.push(entity);
    }

    this.viewer.scene.requestRender();
  }

  private clear(): void {
    if (this.entities.length === 0) return;

    const entities = this.viewer.entities as unknown as {
      remove: (entity: unknown) => boolean;
    };

    for (const entity of this.entities) {
      entities.remove(entity);
    }

    this.entities = [];
    this.viewer.scene.requestRender();
  }
}
