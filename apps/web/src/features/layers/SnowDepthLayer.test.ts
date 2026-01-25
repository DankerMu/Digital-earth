import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    GeographicTilingScheme: vi.fn((options?: unknown) => ({ kind: 'geographic', options })),
    Rectangle: {
      fromDegrees: vi.fn((west: number, south: number, east: number, north: number) => ({
        west,
        south,
        east,
        north,
      })),
    },
    UrlTemplateImageryProvider: vi.fn(function (options: unknown) {
      return { kind: 'url-template', options };
    }),
    ImageryLayer: vi.fn(function (provider: unknown, options: unknown) {
      return { kind: 'imagery-layer', provider, ...(options as Record<string, unknown>) };
    }),
    TextureMinificationFilter: { LINEAR: 'linear', NEAREST: 'nearest' },
    TextureMagnificationFilter: { LINEAR: 'linear', NEAREST: 'nearest' },
  };
});

import { GeographicTilingScheme, ImageryLayer, Rectangle, UrlTemplateImageryProvider } from 'cesium';
import { SnowDepthLayer } from './SnowDepthLayer';

function makeViewer() {
  return {
    imageryLayers: {
      add: vi.fn(),
      remove: vi.fn(),
    },
    scene: {
      requestRender: vi.fn(),
    },
  };
}

describe('SnowDepthLayer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates an ImageryLayer backed by CLDAS tiles and applies opacity/visibility', () => {
    const viewer = makeViewer();

    new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:59:00Z',
      variable: 'snow-depth',
      opacity: 0.7,
      visible: true,
      zIndex: 50,
      rectangle: { west: 100, south: 20, east: 110, north: 30 },
    });

    expect(vi.mocked(GeographicTilingScheme)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(Rectangle.fromDegrees)).toHaveBeenCalledWith(100, 20, 110, 30);

    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: expect.stringContaining('/api/v1/tiles/cldas/'),
        minimumLevel: 8,
        maximumLevel: 10,
        tileWidth: 256,
        tileHeight: 256,
        rectangle: expect.objectContaining({ west: 100, south: 20, east: 110, north: 30 }),
      }),
    );

    const providerUrl = (
      vi.mocked(UrlTemplateImageryProvider).mock.calls[0]?.[0] as { url?: string }
    )?.url;
    expect(providerUrl).toContain('/20251222T000000Z/');
    expect(providerUrl).toContain('/SNOD/');

    expect(vi.mocked(ImageryLayer)).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'url-template' }),
      expect.objectContaining({ alpha: 0.7, show: true }),
    );
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('uses a lower max tile level for global coverage', () => {
    const viewer = makeViewer();

    new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 1,
      visible: true,
      zIndex: 50,
    });

    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        minimumLevel: 0,
        maximumLevel: 6,
        rectangle: undefined,
      }),
    );
  });

  it('updates opacity and visibility without recreating the layer', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 1,
      visible: true,
      zIndex: 50,
    });

    const imageryLayer = vi.mocked(ImageryLayer).mock.results[0]?.value as {
      alpha?: number;
      show?: boolean;
    };

    viewer.scene.requestRender.mockClear();
    vi.mocked(UrlTemplateImageryProvider).mockClear();
    viewer.imageryLayers.remove.mockClear();

    layer.update({
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 0.4,
      visible: false,
      zIndex: 50,
    });

    expect(viewer.imageryLayers.remove).not.toHaveBeenCalled();
    expect(vi.mocked(UrlTemplateImageryProvider)).not.toHaveBeenCalled();
    expect(imageryLayer.alpha).toBe(0.4);
    expect(imageryLayer.show).toBe(false);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('recreates the layer when the tile template changes', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 0.65,
      visible: true,
      zIndex: 50,
    });

    const firstLayer = layer.layer;
    expect(firstLayer).toBeTruthy();

    layer.update({
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011501',
      variable: 'SNOD',
      opacity: 0.65,
      visible: true,
      zIndex: 50,
    });

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(firstLayer, true);
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2);
    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledTimes(2);
  });

  it('recreates the layer when the coverage rectangle changes', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 1,
      visible: true,
      zIndex: 50,
      rectangle: null,
    });

    const firstLayer = layer.layer;
    expect(firstLayer).toBeTruthy();

    layer.update({
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 1,
      visible: true,
      zIndex: 50,
      rectangle: { west: 0, south: 0, east: 10, north: 10 },
    });

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(firstLayer, true);
  });

  it('clamps invalid opacity values', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 2,
      visible: true,
      zIndex: 50,
    });

    expect(layer.layer?.alpha).toBe(1);

    layer.update({
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: -1,
      visible: true,
      zIndex: 50,
    });

    expect(layer.layer?.alpha).toBe(0);
  });

  it('destroys its Cesium layer and requests render', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 0.5,
      visible: true,
      zIndex: 50,
    });

    const imageryLayer = layer.layer;
    expect(imageryLayer).toBeTruthy();

    viewer.scene.requestRender.mockClear();

    layer.destroy();

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(imageryLayer, true);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
    expect(layer.layer).toBeNull();
  });

  it('rejects updates for a different layer id', () => {
    const viewer = makeViewer();

    const layer = new SnowDepthLayer(viewer as never, {
      id: 'snow-depth',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      variable: 'SNOD',
      opacity: 1,
      visible: true,
      zIndex: 50,
    });

    expect(() =>
      layer.update({
        id: 'other',
        apiBaseUrl: 'http://api.test',
        timeKey: '2024011500',
        variable: 'SNOD',
        opacity: 1,
        visible: true,
        zIndex: 50,
      }),
    ).toThrow('SnowDepthLayer id mismatch');
  });
});
