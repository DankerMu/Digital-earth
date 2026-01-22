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
import { AnalyticsTileLayer } from './AnalyticsTileLayer';

function makeViewer() {
  return {
    imageryLayers: {
      add: vi.fn(),
      remove: vi.fn(),
      raiseToTop: vi.fn(),
    },
    scene: {
      requestRender: vi.fn(),
    },
  };
}

describe('AnalyticsTileLayer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates an ImageryLayer backed by a URL template and applies levels/rectangle', () => {
    const viewer = makeViewer();

    new AnalyticsTileLayer(viewer as never, {
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 0.6,
      visible: true,
      zIndex: 60,
      rectangle: { west: 100, south: 20, east: 110, north: 30 },
      minimumLevel: 8,
      maximumLevel: 10,
      credit: 'Test tiles',
    });

    expect(vi.mocked(GeographicTilingScheme)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(Rectangle.fromDegrees)).toHaveBeenCalledWith(100, 20, 110, 30);

    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: expect.stringContaining('/api/v1/tiles/statistics/'),
        minimumLevel: 8,
        maximumLevel: 10,
        tileWidth: 256,
        tileHeight: 256,
        rectangle: expect.objectContaining({ west: 100, south: 20, east: 110, north: 30 }),
        credit: 'Test tiles',
      }),
    );

    expect(vi.mocked(ImageryLayer)).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'url-template' }),
      expect.objectContaining({ alpha: 0.6, show: true }),
    );
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('updates opacity and visibility without recreating the layer', () => {
    const viewer = makeViewer();

    const layer = new AnalyticsTileLayer(viewer as never, {
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 1,
      visible: true,
      zIndex: 60,
    });

    const imageryLayer = vi.mocked(ImageryLayer).mock.results[0]?.value as {
      alpha?: number;
      show?: boolean;
    };

    viewer.scene.requestRender.mockClear();
    viewer.imageryLayers.remove.mockClear();
    vi.mocked(UrlTemplateImageryProvider).mockClear();

    layer.update({
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 0.25,
      visible: false,
      zIndex: 60,
    });

    expect(viewer.imageryLayers.remove).not.toHaveBeenCalled();
    expect(vi.mocked(UrlTemplateImageryProvider)).not.toHaveBeenCalled();
    expect(imageryLayer.alpha).toBe(0.25);
    expect(imageryLayer.show).toBe(false);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('recreates the layer when the URL template changes', () => {
    const viewer = makeViewer();

    const layer = new AnalyticsTileLayer(viewer as never, {
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 1,
      visible: true,
      zIndex: 60,
    });

    const firstLayer = layer.layer;
    expect(firstLayer).toBeTruthy();

    layer.update({
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/y/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 1,
      visible: true,
      zIndex: 60,
    });

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(firstLayer, true);
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2);
  });

  it('recreates the layer when levels change', () => {
    const viewer = makeViewer();

    const layer = new AnalyticsTileLayer(viewer as never, {
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 1,
      visible: true,
      zIndex: 60,
      minimumLevel: 0,
      maximumLevel: 6,
    });

    const firstLayer = layer.layer;

    layer.update({
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 1,
      visible: true,
      zIndex: 60,
      minimumLevel: 8,
      maximumLevel: 10,
    });

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(firstLayer, true);
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2);
  });

  it('destroys its Cesium layer and requests render', () => {
    const viewer = makeViewer();

    const layer = new AnalyticsTileLayer(viewer as never, {
      id: 'historical',
      urlTemplate: 'http://api.test/api/v1/tiles/statistics/x/{z}/{x}/{y}.png',
      frameKey: 'frame-1',
      opacity: 0.5,
      visible: true,
      zIndex: 60,
    });

    const imageryLayer = layer.layer;
    expect(imageryLayer).toBeTruthy();

    viewer.scene.requestRender.mockClear();

    layer.destroy();

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(imageryLayer, true);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
    expect(layer.layer).toBeNull();
  });
});

