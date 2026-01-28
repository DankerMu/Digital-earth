import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    GeographicTilingScheme: vi.fn((options?: unknown) => ({ kind: 'geographic', options })),
    UrlTemplateImageryProvider: vi.fn(function (options: unknown) {
      const listeners = new Set<(error: unknown) => void>();

      return {
        kind: 'url-template',
        options,
        errorEvent: {
          addEventListener: vi.fn((listener: (error: unknown) => void) => {
            listeners.add(listener);
          }),
          removeEventListener: vi.fn((listener: (error: unknown) => void) => {
            listeners.delete(listener);
          }),
          __mocks: {
            trigger: (error: unknown) => {
              for (const listener of listeners) {
                listener(error);
              }
            },
          },
        },
      };
    }),
    ImageryLayer: vi.fn(function (provider: unknown, options: unknown) {
      return { kind: 'imagery-layer', provider, ...(options as Record<string, unknown>) };
    }),
    TextureMinificationFilter: { LINEAR: 'linear', NEAREST: 'nearest' },
    TextureMagnificationFilter: { LINEAR: 'linear', NEAREST: 'nearest' },
  };
});

import { GeographicTilingScheme, ImageryLayer, UrlTemplateImageryProvider } from 'cesium';
import { PrecipitationLayer } from './PrecipitationLayer';

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

describe('PrecipitationLayer', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates an ImageryLayer backed by precipitation tiles and applies opacity/visibility', () => {
    const viewer = makeViewer();

    new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2025-12-22T00:00:00Z',
      opacity: 0.9,
      visible: true,
      zIndex: 30,
      threshold: 1.25,
    });

    expect(vi.mocked(GeographicTilingScheme)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(GeographicTilingScheme)).toHaveBeenCalledWith(
      expect.objectContaining({ numberOfLevelZeroTilesX: 1, numberOfLevelZeroTilesY: 1 }),
    );
    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: expect.stringContaining('/api/v1/tiles/ecmwf/precip_amount/'),
        tilingScheme: expect.objectContaining({
          kind: 'geographic',
          options: expect.objectContaining({
            numberOfLevelZeroTilesX: 1,
            numberOfLevelZeroTilesY: 1,
          }),
        }),
        maximumLevel: 22,
        tileWidth: 256,
        tileHeight: 256,
      }),
    );

    const providerUrl = (
      vi.mocked(UrlTemplateImageryProvider).mock.calls[0]?.[0] as { url?: string }
    )?.url;
    expect(providerUrl).toContain('/precip_amount/');
    expect(providerUrl).toContain('threshold=1.25');

    const provider = vi.mocked(UrlTemplateImageryProvider).mock.results[0]?.value as {
      errorEvent?: { addEventListener?: ReturnType<typeof vi.fn> };
    };
    expect(provider.errorEvent?.addEventListener).toHaveBeenCalledTimes(1);
    expect(provider.errorEvent?.addEventListener).toHaveBeenCalledWith(expect.any(Function));

    expect(vi.mocked(ImageryLayer)).toHaveBeenCalledWith(
      expect.objectContaining({ kind: 'url-template' }),
      expect.objectContaining({ alpha: 0.9, show: true }),
    );

    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(1);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);

    const imageryLayer = vi.mocked(ImageryLayer).mock.results[0]?.value as {
      minificationFilter?: unknown;
      magnificationFilter?: unknown;
    };
    expect(imageryLayer.minificationFilter).toBe('nearest');
    expect(imageryLayer.magnificationFilter).toBe('nearest');
  });

  it('updates opacity and visibility without recreating the layer', () => {
    const viewer = makeViewer();

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: 0,
    });

    const imageryLayer = vi.mocked(ImageryLayer).mock.results[0]?.value as {
      alpha?: number;
      show?: boolean;
    };

    viewer.scene.requestRender.mockClear();
    vi.mocked(UrlTemplateImageryProvider).mockClear();
    viewer.imageryLayers.remove.mockClear();

    layer.update({
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 0.25,
      visible: false,
      zIndex: 30,
      threshold: 0,
    });

    expect(viewer.imageryLayers.remove).not.toHaveBeenCalled();
    expect(vi.mocked(UrlTemplateImageryProvider)).not.toHaveBeenCalled();
    expect(imageryLayer.alpha).toBe(0.25);
    expect(imageryLayer.show).toBe(false);
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('recreates the layer when the tile template changes', () => {
    const viewer = makeViewer();

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: null,
    });

    const firstLayer = layer.layer;
    expect(firstLayer).toBeTruthy();

    layer.update({
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: 2,
    });

    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(firstLayer, true);
    expect(viewer.imageryLayers.add).toHaveBeenCalledTimes(2);
    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledTimes(2);
  });

  it('clamps invalid opacity values', () => {
    const viewer = makeViewer();

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 2,
      visible: true,
      zIndex: 30,
      threshold: null,
    });

    expect(layer.layer?.alpha).toBe(1);

    layer.update({
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: -1,
      visible: true,
      zIndex: 30,
      threshold: null,
    });

    expect(layer.layer?.alpha).toBe(0);
  });

  it('destroys its Cesium layer and requests render', () => {
    const viewer = makeViewer();

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: null,
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

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: null,
    });

    expect(() =>
      layer.update({
        id: 'other',
        apiBaseUrl: 'http://api.test',
        timeKey: '2024011500',
        opacity: 1,
        visible: true,
        zIndex: 30,
        threshold: null,
      }),
    ).toThrow('PrecipitationLayer id mismatch');
  });

  it('logs once when precipitation tiles are missing (404)', () => {
    const viewer = makeViewer();
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    try {
      new PrecipitationLayer(viewer as never, {
        id: 'precipitation',
        apiBaseUrl: 'http://api.test',
        timeKey: '2024011500',
        opacity: 1,
        visible: true,
        zIndex: 30,
        threshold: null,
      });

      const provider = vi.mocked(UrlTemplateImageryProvider).mock.results[0]?.value as {
        errorEvent?: { __mocks?: { trigger?: (error: unknown) => void } };
      };

      provider.errorEvent?.__mocks?.trigger?.({ error: { statusCode: 404 }, x: 0, y: 0, level: 0 });
      provider.errorEvent?.__mocks?.trigger?.({ error: { statusCode: 404 }, x: 1, y: 1, level: 0 });

      const warnCalls = warnSpy.mock.calls.filter(
        ([message]) => message === '[Digital Earth] precipitation tiles missing (404)',
      );
      expect(warnCalls).toHaveLength(1);
      expect(warnCalls[0]?.[1]).toEqual(
        expect.objectContaining({
          statusCode: 404,
          urlTemplate: expect.stringContaining('/api/v1/tiles/ecmwf/precip_amount/'),
        }),
      );
    } finally {
      warnSpy.mockRestore();
    }
  });

  it('removes its provider error listener on destroy', () => {
    const viewer = makeViewer();

    const layer = new PrecipitationLayer(viewer as never, {
      id: 'precipitation',
      apiBaseUrl: 'http://api.test',
      timeKey: '2024011500',
      opacity: 1,
      visible: true,
      zIndex: 30,
      threshold: null,
    });

    const provider = vi.mocked(UrlTemplateImageryProvider).mock.results[0]?.value as {
      errorEvent?: { removeEventListener?: ReturnType<typeof vi.fn> };
    };

    layer.destroy();

    expect(provider.errorEvent?.removeEventListener).toHaveBeenCalledTimes(1);
    expect(provider.errorEvent?.removeEventListener).toHaveBeenCalledWith(expect.any(Function));
    expect(viewer.scene.requestRender).toHaveBeenCalled();
  });
});
