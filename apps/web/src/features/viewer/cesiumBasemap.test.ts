import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    WebMapTileServiceImageryProvider: vi.fn((options) => ({ kind: 'wmts', options })),
    UrlTemplateImageryProvider: vi.fn((options) => ({ kind: 'url-template', options })),
    WebMercatorTilingScheme: vi.fn(() => ({ kind: 'web-mercator' })),
    IonWorldImageryStyle: {
      AERIAL: 'AERIAL',
      AERIAL_WITH_LABELS: 'AERIAL_WITH_LABELS',
      ROAD: 'ROAD',
    },
    createWorldImageryAsync: vi.fn(async (options) => ({ kind: 'ion-world-imagery', options })),
  };
});

import {
  IonWorldImageryStyle,
  UrlTemplateImageryProvider,
  WebMapTileServiceImageryProvider,
  WebMercatorTilingScheme,
  createWorldImageryAsync,
} from 'cesium';

import { getBasemapById } from '../../config/basemaps';
import { createImageryProviderForBasemapAsync, setViewerBasemap } from './cesiumBasemap';

describe('cesiumBasemap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates a WMTS imagery provider for the NASA basemap', async () => {
    const basemap = getBasemapById('nasa-gibs-blue-marble');
    expect(basemap).toBeTruthy();

    await createImageryProviderForBasemapAsync(basemap!);

    expect(vi.mocked(WebMapTileServiceImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
        layer: 'BlueMarble_NextGeneration',
        tileMatrixSetID: 'GoogleMapsCompatible_Level8',
      }),
    );
  });

  it('normalizes TMS templates to use reverseY', async () => {
    await createImageryProviderForBasemapAsync({
      kind: 'url-template',
      id: 'test',
      label: 'test',
      credit: 'test',
      urlTemplate: 'https://example.com/{z}/{x}/{y}.png',
      scheme: 'tms',
      maximumLevel: 2,
    });

    expect(vi.mocked(WebMercatorTilingScheme)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(UrlTemplateImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'https://example.com/{z}/{x}/{reverseY}.png',
        maximumLevel: 2,
      }),
    );
  });

  it('creates a Cesium ion world imagery provider', async () => {
    await createImageryProviderForBasemapAsync({
      kind: 'ion',
      id: 'ion-world-imagery',
      label: 'Bing Maps (Cesium ion)',
      credit: 'Cesium ion / Bing Maps',
      style: 'aerial-with-labels',
    });

    expect(vi.mocked(createWorldImageryAsync)).toHaveBeenCalledWith({
      style: IonWorldImageryStyle.AERIAL_WITH_LABELS,
    });
  });

  it('replaces the viewer base layer and requests render', async () => {
    const basemap = getBasemapById('s2cloudless-2021');
    expect(basemap).toBeTruthy();

    const baseLayer = { layer: true };
    const viewer = {
      imageryLayers: {
        get: vi.fn(() => baseLayer),
        remove: vi.fn(),
        addImageryProvider: vi.fn(),
      },
      scene: {
        requestRender: vi.fn(),
      },
    };

    await expect(setViewerBasemap(viewer as unknown as never, basemap!)).resolves.toBe(true);

    expect(viewer.imageryLayers.get).toHaveBeenCalledWith(0);
    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(baseLayer, true);
    expect(viewer.imageryLayers.addImageryProvider).toHaveBeenCalledWith(
      expect.anything(),
      0,
    );
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });

  it('keeps the current viewer base layer when an ion provider fails to load', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.mocked(createWorldImageryAsync).mockRejectedValueOnce(new Error('boom'));

    const baseLayer = { layer: true };
    const viewer = {
      imageryLayers: {
        get: vi.fn(() => baseLayer),
        remove: vi.fn(),
        addImageryProvider: vi.fn(),
      },
      scene: {
        requestRender: vi.fn(),
      },
    };

    await expect(
      setViewerBasemap(viewer as unknown as never, {
        kind: 'ion',
        id: 'ion-world-imagery',
        label: 'Bing Maps (Cesium ion)',
        credit: 'Cesium ion / Bing Maps',
      }),
    ).resolves.toBe(false);

    expect(viewer.imageryLayers.remove).not.toHaveBeenCalled();
    expect(viewer.imageryLayers.addImageryProvider).not.toHaveBeenCalled();

    warn.mockRestore();
  });
});
