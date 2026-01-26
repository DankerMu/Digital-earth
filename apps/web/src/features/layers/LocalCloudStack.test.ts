import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const withAlpha = vi.fn((alpha: number) => ({ kind: 'color', alpha }));

  const Color = {
    WHITE: {
      withAlpha,
    },
  };

  const EllipsoidSurfaceAppearance = vi.fn(function (options: unknown) {
    return { kind: 'appearance', options };
  }) as unknown as { VERTEX_FORMAT: string };
  (EllipsoidSurfaceAppearance as { VERTEX_FORMAT: string }).VERTEX_FORMAT = 'vertex-format';

  const GeometryInstance = vi.fn(function (options: unknown) {
    return { kind: 'geometry-instance', options };
  });

  const Material = {
    fromType: vi.fn((type: string, uniforms: Record<string, unknown>) => ({
      kind: 'material',
      type,
      uniforms: { ...uniforms },
    })),
  };

  const Primitive = vi.fn(function (options: Record<string, unknown>) {
    return { kind: 'primitive', ...options };
  });

  const Rectangle = {
    fromDegrees: vi.fn((west: number, south: number, east: number, north: number) => ({
      west,
      south,
      east,
      north,
    })),
  };

  const RectangleGeometry = vi.fn(function (options: unknown) {
    return { kind: 'rectangle-geometry', options };
  });

  return {
    Color,
    EllipsoidSurfaceAppearance,
    GeometryInstance,
    Material,
    Primitive,
    Rectangle,
    RectangleGeometry,
  };
});

import {
  Color,
  EllipsoidSurfaceAppearance,
  GeometryInstance,
  Material,
  Primitive,
  Rectangle,
  RectangleGeometry,
} from 'cesium';

import type { LayerConfig } from '../../state/layerManager';
import { LocalCloudStack } from './LocalCloudStack';

class FakeImage {
  src = '';
  crossOrigin: string | null = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
}

function makeViewer(options: { cameraHeightMeters?: number } = {}) {
  const primitives = {
    add: vi.fn(),
    remove: vi.fn(),
  };

  return {
    scene: {
      primitives,
      requestRender: vi.fn(),
    },
    ...(typeof options.cameraHeightMeters === 'number'
      ? { camera: { positionCartographic: { height: options.cameraHeightMeters } } }
      : {}),
  };
}

describe('LocalCloudStack', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    vi.stubGlobal('Image', FakeImage as never);
  });

  it('creates 3x3 primitives for each visible cloud layer and fills XYZ url placeholders', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 180,
      lat: 90,
      surfaceHeightMeters: 10,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.5,
          visible: true,
          zIndex: 0,
        },
        {
          id: 'ignored-temp',
          type: 'temperature',
          variable: 'TMP',
          opacity: 1,
          visible: true,
          zIndex: 0,
        },
        {
          id: 'ignored-hidden',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.5,
          visible: false,
          zIndex: 0,
        },
        {
          id: 'ignored-zero-opacity',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(9);
    expect(vi.mocked(Primitive)).toHaveBeenCalledTimes(9);
    expect(vi.mocked(Material.fromType)).toHaveBeenCalledTimes(9);
    expect(vi.mocked(Rectangle.fromDegrees)).toHaveBeenCalledTimes(9);
    expect(vi.mocked(RectangleGeometry)).toHaveBeenCalledTimes(9);
    expect(vi.mocked(GeometryInstance)).toHaveBeenCalledTimes(9);
    expect(vi.mocked(EllipsoidSurfaceAppearance)).toHaveBeenCalledTimes(9);

    const imageUrls = vi
      .mocked(Material.fromType)
      .mock.calls.map((call) => {
        const image = (call[1] as { image?: unknown } | undefined)?.image;
        if (typeof image === 'string') return image;
        if (image && typeof (image as { src?: unknown }).src === 'string') return (image as { src: string }).src;
        return '';
      });

    expect(imageUrls.every((url) => url.length > 0)).toBe(true);
    expect(imageUrls.some((url) => url.includes('/api/v1/tiles/ecmwf/tcc/'))).toBe(true);
    expect(imageUrls.some((url) => url.includes('/6/0/'))).toBe(true);

    for (const url of imageUrls) {
      expect(url).not.toContain('{z}');
      expect(url).not.toContain('{x}');
      expect(url).not.toContain('{y}');
    }

    expect(vi.mocked(Color.WHITE.withAlpha)).toHaveBeenCalledWith(0.5);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('increases tile zoom/radius near ground for extra detail', () => {
    const viewer = makeViewer({ cameraHeightMeters: 2000 });
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 180,
      lat: 90,
      surfaceHeightMeters: 0,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.75,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(25);

    const imageUrls = vi
      .mocked(Material.fromType)
      .mock.calls.map((call) => {
        const image = (call[1] as { image?: unknown } | undefined)?.image;
        if (typeof image === 'string') return image;
        if (image && typeof (image as { src?: unknown }).src === 'string') return (image as { src: string }).src;
        return '';
      });

    expect(imageUrls.some((url) => url.includes('/10/'))).toBe(true);
  });

  it('reuses existing primitives when the tile key is unchanged and updates opacity via uniforms', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    const baseUpdate = {
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 12.25,
      lat: 43.4,
      surfaceHeightMeters: 250,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.6,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    };

    stack.update(baseUpdate);

    const firstMaterial = vi.mocked(Material.fromType).mock.results[0]?.value as {
      uniforms?: { color?: unknown };
    };
    const firstPrimitive = vi.mocked(Primitive).mock.results[0]?.value as { show?: boolean };

    expect(firstMaterial.uniforms?.color).toEqual({ kind: 'color', alpha: 0.6 });

    firstPrimitive.show = false;

    viewer.scene.primitives.add.mockClear();
    viewer.scene.primitives.remove.mockClear();
    viewer.scene.requestRender.mockClear();
    vi.mocked(Material.fromType).mockClear();
    vi.mocked(Primitive).mockClear();
    vi.mocked(Color.WHITE.withAlpha).mockClear();

    stack.update({
      ...baseUpdate,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 0.25,
          visible: true,
          zIndex: 0,
        },
      ],
    });

    expect(viewer.scene.primitives.add).not.toHaveBeenCalled();
    expect(vi.mocked(Material.fromType)).not.toHaveBeenCalled();

    expect(firstMaterial.uniforms?.color).toEqual({ kind: 'color', alpha: 0.25 });
    expect(firstPrimitive.show).toBe(true);

    expect(vi.mocked(Color.WHITE.withAlpha)).toHaveBeenCalledWith(0.25);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('recreates primitives when the tile key changes and includes humidity level tiles', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: -999,
      lat: 999,
      surfaceHeightMeters: -5000,
      layers: [
        {
          id: 'humidity',
          type: 'cloud',
          variable: 'RH',
          level: 700,
          opacity: Number.POSITIVE_INFINITY,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(9);

    const imageUrls = vi
      .mocked(Material.fromType)
      .mock.calls.map((call) => {
        const image = (call[1] as { image?: unknown } | undefined)?.image;
        if (typeof image === 'string') return image;
        if (image && typeof (image as { src?: unknown }).src === 'string') return (image as { src: string }).src;
        return '';
      });

    expect(imageUrls.some((url) => url.includes('/api/v1/tiles/ecmwf/humidity/'))).toBe(true);
    expect(imageUrls.some((url) => url.includes('/700/'))).toBe(true);

    const firstGeometryCall = vi.mocked(RectangleGeometry).mock.calls[0]?.[0] as {
      height?: number;
      vertexFormat?: unknown;
    };
    expect(firstGeometryCall.height).toBe(0);
    expect(firstGeometryCall.vertexFormat).toBe('vertex-format');

    viewer.scene.primitives.add.mockClear();
    viewer.scene.primitives.remove.mockClear();
    vi.mocked(Material.fromType).mockClear();

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T01:00:00Z',
      lon: -999,
      lat: 999,
      surfaceHeightMeters: -5000,
      layers: [
        {
          id: 'humidity',
          type: 'cloud',
          variable: 'RH',
          level: 700,
          opacity: 0.8,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.remove).toHaveBeenCalledTimes(9);
    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(9);
    expect(vi.mocked(Material.fromType)).toHaveBeenCalledTimes(9);
  });

  it('clears primitives when disabled or when no cloud layers are visible', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: false,
      humanModeEnabled: false,
      apiBaseUrl: null,
      timeKey: null,
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [],
    });

    expect(viewer.scene.requestRender).not.toHaveBeenCalled();
    expect(viewer.scene.primitives.remove).not.toHaveBeenCalled();

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    viewer.scene.requestRender.mockClear();
    viewer.scene.primitives.remove.mockClear();

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: false,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.remove).toHaveBeenCalledTimes(9);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);

    viewer.scene.requestRender.mockClear();
    viewer.scene.primitives.remove.mockClear();

    stack.update({
      enabled: false,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [],
    });

    expect(viewer.scene.primitives.remove).not.toHaveBeenCalled();
    expect(viewer.scene.requestRender).not.toHaveBeenCalled();
  });

  it('removes groups that are no longer present in the layer list', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [
        {
          id: 'a',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 1,
        },
        {
          id: 'b',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 2,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.add).toHaveBeenCalledTimes(18);

    viewer.scene.primitives.add.mockClear();
    viewer.scene.primitives.remove.mockClear();
    viewer.scene.requestRender.mockClear();

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 0,
      lat: 0,
      surfaceHeightMeters: 0,
      layers: [
        {
          id: 'a',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 1,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.primitives.add).not.toHaveBeenCalled();
    expect(viewer.scene.primitives.remove).toHaveBeenCalledTimes(9);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('requests a render after a tile image finishes loading', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 180,
      lat: 90,
      surfaceHeightMeters: 10,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);

    const firstImage = vi.mocked(Material.fromType).mock.calls[0]?.[1] as { image?: FakeImage } | undefined;
    firstImage?.image?.onload?.();

    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(2);
  });

  it('uses a human-specific tile material when enabled', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: true,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 180,
      lat: 90,
      surfaceHeightMeters: 10,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    const firstCall = vi.mocked(Material.fromType).mock.calls[0] ?? [];
    expect(firstCall[0]).toBe('LocalCloudTileHuman');
    expect(firstCall[1]).toEqual(
      expect.objectContaining({
        edgeFadeStart: expect.any(Number),
        edgeFadeWidth: expect.any(Number),
        edgeFadeMinAlpha: expect.any(Number),
        edgeFadeMaxAlpha: expect.any(Number),
      }),
    );
  });

  it('does not throw when viewer is missing during teardown', () => {
    const viewer = makeViewer();
    const stack = new LocalCloudStack(viewer as never);

    stack.update({
      enabled: true,
      humanModeEnabled: false,
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      lon: 180,
      lat: 90,
      surfaceHeightMeters: 10,
      layers: [
        {
          id: 'cloud-1',
          type: 'cloud',
          variable: 'tcc',
          opacity: 1,
          visible: true,
          zIndex: 0,
        },
      ] satisfies LayerConfig[],
    });

    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);

    (stack as unknown as { viewer?: unknown }).viewer = undefined;

    expect(() => stack.destroy()).not.toThrow();
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });
});
