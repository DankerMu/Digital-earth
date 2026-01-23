import type { VolumePackDecoded } from '../../lib/volumePack';

export type VolumeAtlas = {
  atlas: Uint8Array;
  atlasWidth: number;
  atlasHeight: number;
  gridCols: number;
  gridRows: number;
  sliceWidth: number;
  sliceHeight: number;
  depth: number;
  minValue: number;
  maxValue: number;
};

function clamp01(value: number): number {
  if (value <= 0) return 0;
  if (value >= 1) return 1;
  return value;
}

function toFiniteNumber(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return value;
}

export function buildVolumeAtlas(decoded: VolumePackDecoded): VolumeAtlas {
  const [depth, sliceHeight, sliceWidth] = decoded.shape;
  const gridCols = Math.ceil(Math.sqrt(depth));
  const gridRows = Math.ceil(depth / gridCols);
  const atlasWidth = gridCols * sliceWidth;
  const atlasHeight = gridRows * sliceHeight;

  const atlas = new Uint8Array(atlasWidth * atlasHeight);
  let minValue = Number.POSITIVE_INFINITY;
  let maxValue = Number.NEGATIVE_INFINITY;

  const sliceStride = sliceWidth * sliceHeight;
  const scale = decoded.scale;
  const offset = decoded.offset;
  const data = decoded.data as unknown as ArrayLike<number>;

  for (let z = 0; z < depth; z += 1) {
    const tileX = z % gridCols;
    const tileY = Math.floor(z / gridCols);
    const tileOriginX = tileX * sliceWidth;
    const tileOriginY = tileY * sliceHeight;

    const sliceOffset = z * sliceStride;

    for (let y = 0; y < sliceHeight; y += 1) {
      const destRowStart = (tileOriginY + y) * atlasWidth + tileOriginX;
      const srcRowStart = sliceOffset + y * sliceWidth;

      for (let x = 0; x < sliceWidth; x += 1) {
        const rawValue = data[srcRowStart + x];
        const normalizedRaw = toFiniteNumber(rawValue);
        const value = (normalizedRaw ?? 0) * scale + offset;

        if (value < minValue) minValue = value;
        if (value > maxValue) maxValue = value;

        atlas[destRowStart + x] = Math.round(clamp01(value) * 255);
      }
    }
  }

  if (!Number.isFinite(minValue)) minValue = 0;
  if (!Number.isFinite(maxValue)) maxValue = 0;

  return {
    atlas,
    atlasWidth,
    atlasHeight,
    gridCols,
    gridRows,
    sliceWidth,
    sliceHeight,
    depth,
    minValue,
    maxValue,
  };
}

export type AtlasCanvas = {
  canvas: HTMLCanvasElement;
  approxBytes: number;
};

export function buildAtlasCanvas(atlas: Uint8Array, width: number, height: number): AtlasCanvas {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Voxel cloud atlas requires CanvasRenderingContext2D');
  }

  const rgba = new Uint8ClampedArray(width * height * 4);
  for (let i = 0; i < atlas.length; i += 1) {
    const value = atlas[i]!;
    const base = i * 4;
    rgba[base] = value;
    rgba[base + 1] = value;
    rgba[base + 2] = value;
    rgba[base + 3] = 255;
  }

  const ImageDataCtor = (globalThis as unknown as { ImageData?: typeof ImageData }).ImageData;
  const createImageData = (ctx as unknown as { createImageData?: (w: number, h: number) => ImageData })
    .createImageData;

  const imageData =
    typeof ImageDataCtor === 'function'
      ? new ImageDataCtor(rgba, width, height)
      : typeof createImageData === 'function'
        ? (() => {
            const next = createImageData(width, height);
            next.data.set(rgba);
            return next;
          })()
        : ({ data: rgba, width, height } as unknown as ImageData);

  ctx.putImageData(imageData, 0, 0);
  return { canvas, approxBytes: rgba.byteLength };
}
