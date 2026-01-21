export type Rgba = {
  r: number;
  g: number;
  b: number;
  a: number;
};

export type PrecipitationKind = 'rain' | 'snow' | 'none';

export type WeatherSample = {
  precipitationMm: number | null;
  precipitationIntensity: number;
  precipitationKind: PrecipitationKind;
  temperatureC: number | null;
};

export type TileTemplate = {
  urlTemplate: string;
  tileSize?: number;
};

export type WeatherSamplerConfig = {
  precipitation: TileTemplate;
  temperature: TileTemplate;
  zoom: number;
  levelZeroTilesX?: number;
  levelZeroTilesY?: number;
  fetchImageData?: (url: string, options: { signal?: AbortSignal }) => Promise<ImageData>;
};

type Rgb = {
  r: number;
  g: number;
  b: number;
};

type ColorStop = {
  value: number;
  color: Rgb;
};

const TEMPERATURE_STOPS: ColorStop[] = [
  { value: -20, color: { r: 0x3b, g: 0x82, b: 0xf6 } },
  { value: 0, color: { r: 0xff, g: 0xff, b: 0xff } },
  { value: 40, color: { r: 0xef, g: 0x44, b: 0x44 } },
];

const PRECIPITATION_STOPS: ColorStop[] = [
  { value: 0, color: { r: 0xff, g: 0xff, b: 0xff } },
  { value: 10, color: { r: 0x93, g: 0xc5, b: 0xfd } },
  { value: 25, color: { r: 0x3b, g: 0x82, b: 0xf6 } },
  { value: 50, color: { r: 0x1d, g: 0x4e, b: 0xd8 } },
  { value: 100, color: { r: 0x7c, g: 0x3a, b: 0xed } },
];

type TileBoundsDegrees = {
  west: number;
  south: number;
  east: number;
  north: number;
};

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function clamp01(value: number): number {
  return clamp(value, 0, 1);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

export function precipitationMmToIntensity(precipitationMm: number | null): number {
  if (!isFiniteNumber(precipitationMm)) return 0;
  if (precipitationMm <= 0) return 0;
  const normalized = Math.log10(precipitationMm + 1) / Math.log10(101);
  return clamp01(normalized);
}

export function temperatureCToPrecipitationKind(
  precipitationIntensity: number,
  temperatureC: number | null,
): PrecipitationKind {
  if (precipitationIntensity <= 0) return 'none';
  if (!isFiniteNumber(temperatureC)) return 'rain';
  return temperatureC <= 0 ? 'snow' : 'rain';
}

function valueFromGradientRgba(rgba: Rgba, stops: ColorStop[]): number | null {
  if (!isFiniteNumber(rgba.a) || rgba.a <= 0) return null;

  const point = { r: rgba.r, g: rgba.g, b: rgba.b };
  let bestDist = Number.POSITIVE_INFINITY;
  let bestValue: number | null = null;

  for (let i = 0; i < stops.length - 1; i += 1) {
    const left = stops[i]!;
    const right = stops[i + 1]!;

    const v0 = left.value;
    const v1 = right.value;
    const c0 = left.color;
    const c1 = right.color;
    const dx = c1.r - c0.r;
    const dy = c1.g - c0.g;
    const dz = c1.b - c0.b;
    const denom = dx * dx + dy * dy + dz * dz;

    let t = 0;
    if (denom > 0) {
      t =
        ((point.r - c0.r) * dx + (point.g - c0.g) * dy + (point.b - c0.b) * dz) / denom;
    }
    t = clamp01(t);

    const pr = c0.r + t * dx;
    const pg = c0.g + t * dy;
    const pb = c0.b + t * dz;

    const dr = point.r - pr;
    const dg = point.g - pg;
    const db = point.b - pb;
    const dist = dr * dr + dg * dg + db * db;
    if (dist >= bestDist) continue;

    bestDist = dist;
    bestValue = v0 + t * (v1 - v0);
  }

  return bestValue;
}

function fillUrlTemplate(urlTemplate: string, params: { z: number; x: number; y: number }): string {
  return urlTemplate
    .replaceAll('{z}', String(params.z))
    .replaceAll('{x}', String(params.x))
    .replaceAll('{y}', String(params.y));
}

function tilesAtLevel(level: number, levelZeroTiles: number): number {
  if (!Number.isFinite(level) || level < 0) return levelZeroTiles;
  const scale = 2 ** Math.floor(level);
  return levelZeroTiles * scale;
}

export function tileXYForLonLatDegrees(options: {
  lon: number;
  lat: number;
  zoom: number;
  levelZeroTilesX: number;
  levelZeroTilesY: number;
}): { x: number; y: number } {
  const lon = clamp(options.lon, -180, 180);
  const lat = clamp(options.lat, -90, 90);
  const xTiles = tilesAtLevel(options.zoom, options.levelZeroTilesX);
  const yTiles = tilesAtLevel(options.zoom, options.levelZeroTilesY);

  const x = Math.floor(((lon + 180) / 360) * xTiles);
  const y = Math.floor(((90 - lat) / 180) * yTiles);

  return {
    x: clamp(x, 0, xTiles - 1),
    y: clamp(y, 0, yTiles - 1),
  };
}

export function tileBoundsForXY(options: {
  x: number;
  y: number;
  zoom: number;
  levelZeroTilesX: number;
  levelZeroTilesY: number;
}): TileBoundsDegrees {
  const xTiles = tilesAtLevel(options.zoom, options.levelZeroTilesX);
  const yTiles = tilesAtLevel(options.zoom, options.levelZeroTilesY);
  const tileWidth = 360 / xTiles;
  const tileHeight = 180 / yTiles;

  const west = -180 + options.x * tileWidth;
  const east = west + tileWidth;
  const north = 90 - options.y * tileHeight;
  const south = north - tileHeight;

  return { west, south, east, north };
}

function pixelXYForLonLatDegrees(options: {
  lon: number;
  lat: number;
  bounds: TileBoundsDegrees;
  tileSize: number;
}): { x: number; y: number } {
  const lon = clamp(options.lon, options.bounds.west, options.bounds.east);
  const lat = clamp(options.lat, options.bounds.south, options.bounds.north);

  const u =
    options.bounds.east === options.bounds.west
      ? 0
      : (lon - options.bounds.west) / (options.bounds.east - options.bounds.west);
  const v =
    options.bounds.north === options.bounds.south
      ? 0
      : (options.bounds.north - lat) / (options.bounds.north - options.bounds.south);

  const x = Math.floor(u * options.tileSize);
  const y = Math.floor(v * options.tileSize);

  return {
    x: clamp(x, 0, options.tileSize - 1),
    y: clamp(y, 0, options.tileSize - 1),
  };
}

function rgbaAt(imageData: ImageData, x: number, y: number): Rgba {
  const px = clamp(x, 0, imageData.width - 1);
  const py = clamp(y, 0, imageData.height - 1);
  const idx = (py * imageData.width + px) * 4;
  const data = imageData.data;
  return {
    r: data[idx] ?? 0,
    g: data[idx + 1] ?? 0,
    b: data[idx + 2] ?? 0,
    a: data[idx + 3] ?? 0,
  };
}

async function defaultFetchImageData(url: string, options: { signal?: AbortSignal }): Promise<ImageData> {
  const response = await fetch(url, { method: 'GET', signal: options.signal });
  if (!response.ok) {
    throw new Error(`Failed to load tile: ${response.status}`);
  }

  const blob = await response.blob();
  const image = await loadImage(blob);
  const canvas = createCanvas(image.width, image.height);
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) {
    throw new Error('Canvas 2D context unavailable');
  }

  ctx.drawImage(image as CanvasImageSource, 0, 0);
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

type DrawableImage = {
  width: number;
  height: number;
};

async function loadImage(blob: Blob): Promise<DrawableImage> {
  if (typeof createImageBitmap === 'function') {
    return createImageBitmap(blob);
  }

  const url = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.decoding = 'async';
    img.src = url;
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error('Failed to decode image'));
    });
    return img;
  } finally {
    URL.revokeObjectURL(url);
  }
}

type CanvasLike = {
  width: number;
  height: number;
  getContext: (
    contextId: '2d',
    options?: CanvasRenderingContext2DSettings,
  ) => CanvasRenderingContext2D | null;
};

function createCanvas(width: number, height: number): CanvasLike {
  if (typeof OffscreenCanvas !== 'undefined') {
    return new OffscreenCanvas(width, height) as unknown as CanvasLike;
  }
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  return canvas;
}

export function createWeatherSampler(config: WeatherSamplerConfig): {
  sample: (options: { lon: number; lat: number; signal?: AbortSignal }) => Promise<WeatherSample>;
} {
  const tileSizePrecip = config.precipitation.tileSize ?? 256;
  const tileSizeTemp = config.temperature.tileSize ?? 256;
  const levelZeroTilesX = config.levelZeroTilesX ?? 2;
  const levelZeroTilesY = config.levelZeroTilesY ?? 1;
  const fetchImageData = config.fetchImageData ?? defaultFetchImageData;

  let cachedPrecip: { url: string; image: ImageData } | null = null;
  let cachedTemp: { url: string; image: ImageData } | null = null;

  const getImage = async (
    url: string,
    cache: typeof cachedPrecip,
    signal: AbortSignal | undefined,
  ): Promise<{ image: ImageData; cache: { url: string; image: ImageData } }> => {
    if (cache?.url === url) return { image: cache.image, cache };
    const image = await fetchImageData(url, { signal });
    return { image, cache: { url, image } };
  };

  const sample = async (options: {
    lon: number;
    lat: number;
    signal?: AbortSignal;
  }): Promise<WeatherSample> => {
    const { lon, lat, signal } = options;
    const { x, y } = tileXYForLonLatDegrees({
      lon,
      lat,
      zoom: config.zoom,
      levelZeroTilesX,
      levelZeroTilesY,
    });

    const precipUrl = fillUrlTemplate(config.precipitation.urlTemplate, { z: config.zoom, x, y });
    const tempUrl = fillUrlTemplate(config.temperature.urlTemplate, { z: config.zoom, x, y });

    const bounds = tileBoundsForXY({ x, y, zoom: config.zoom, levelZeroTilesX, levelZeroTilesY });
    const pxPrecip = pixelXYForLonLatDegrees({ lon, lat, bounds, tileSize: tileSizePrecip });
    const pxTemp = pixelXYForLonLatDegrees({ lon, lat, bounds, tileSize: tileSizeTemp });

    const precipResult = await getImage(precipUrl, cachedPrecip, signal);
    cachedPrecip = precipResult.cache;
    const tempResult = await getImage(tempUrl, cachedTemp, signal);
    cachedTemp = tempResult.cache;

    const precipRgba = rgbaAt(precipResult.image, pxPrecip.x, pxPrecip.y);
    const tempRgba = rgbaAt(tempResult.image, pxTemp.x, pxTemp.y);

    const precipitationMm = valueFromGradientRgba(precipRgba, PRECIPITATION_STOPS);
    const temperatureC = valueFromGradientRgba(tempRgba, TEMPERATURE_STOPS);
    const precipitationIntensity = precipitationMmToIntensity(precipitationMm);
    const precipitationKind = temperatureCToPrecipitationKind(precipitationIntensity, temperatureC);

    return {
      precipitationMm,
      precipitationIntensity,
      precipitationKind,
      temperatureC,
    };
  };

  return { sample };
}

