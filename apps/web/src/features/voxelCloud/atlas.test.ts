import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { VolumePackDecoded } from '../../lib/volumePack';
import { MAX_ATLAS_PIXELS, buildAtlasCanvas, buildVolumeAtlas } from './atlas';

function makeDecoded(): VolumePackDecoded<Float32Array> {
  const shape: [number, number, number] = [2, 2, 2];
  const values = Float32Array.from(
    [0, 0.25, 0.5, 0.75, 1.0, 0.1, 0.2, 0.3],
  );
  return {
    header: { shape, dtype: 'float32', scale: 1, offset: 0, compression: 'zstd' },
    shape,
    dtype: 'float32',
    scale: 1,
    offset: 0,
    data: values,
  };
}

describe('buildVolumeAtlas', () => {
  it('packs slices into a 2D atlas', () => {
    const decoded = makeDecoded();
    const atlas = buildVolumeAtlas(decoded);

    expect(atlas.depth).toBe(2);
    expect(atlas.sliceWidth).toBe(2);
    expect(atlas.sliceHeight).toBe(2);
    expect(atlas.gridCols).toBe(2);
    expect(atlas.gridRows).toBe(1);
    expect(atlas.atlasWidth).toBe(4);
    expect(atlas.atlasHeight).toBe(2);
    expect(atlas.atlas.length).toBe(8);

    // First slice goes in the left 2x2.
    expect(atlas.atlas[0]).toBe(0);
    expect(atlas.atlas[1]).toBe(Math.round(0.25 * 255));
    expect(atlas.atlas[4]).toBe(Math.round(0.5 * 255));

    // Second slice goes in the right 2x2.
    expect(atlas.atlas[2]).toBe(255);
    expect(atlas.atlas[3]).toBe(Math.round(0.1 * 255));
    expect(atlas.atlas[6]).toBe(Math.round(0.2 * 255));
  });

  it('throws when the atlas exceeds the maximum size', () => {
    const decoded = {
      header: { shape: [1, 4096, 4097], dtype: 'uint8', scale: 1, offset: 0, compression: 'zstd' },
      shape: [1, 4096, 4097],
      dtype: 'uint8',
      scale: 1,
      offset: 0,
      data: new Uint8Array(0),
    } satisfies VolumePackDecoded;

    expect(() => buildVolumeAtlas(decoded)).toThrow(/MAX_ATLAS_PIXELS/);
  });
});

describe('buildAtlasCanvas', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders grayscale pixels into a canvas', () => {
    const putImageData = vi.fn();
    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (() =>
        ({
          putImageData,
        }) satisfies Partial<CanvasRenderingContext2D>) as unknown as HTMLCanvasElement['getContext'],
    );

    const atlas = new Uint8Array([0, 10, 20, 30]);
    const { canvas, approxBytes } = buildAtlasCanvas(atlas, 2, 2);

    expect(canvas.width).toBe(2);
    expect(canvas.height).toBe(2);
    expect(approxBytes).toBe(2 * 2 * 4);
    expect(putImageData).toHaveBeenCalledTimes(1);
  });

  it('throws when CanvasRenderingContext2D is unavailable', () => {
    (HTMLCanvasElement.prototype.getContext as unknown as ReturnType<typeof vi.fn>).mockImplementation(
      (() => null) as unknown as HTMLCanvasElement['getContext'],
    );

    expect(() => buildAtlasCanvas(new Uint8Array([0]), 1, 1)).toThrow(/CanvasRenderingContext2D/);
  });

  it('throws when the atlas exceeds the maximum size', () => {
    expect(() => buildAtlasCanvas(new Uint8Array(0), MAX_ATLAS_PIXELS + 1, 1)).toThrow(/MAX_ATLAS_PIXELS/);
  });
});
