import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  return {
    WebMapTileServiceImageryProvider: vi.fn((options) => ({ kind: 'wmts', options })),
    UrlTemplateImageryProvider: vi.fn((options) => ({ kind: 'url-template', options })),
    WebMercatorTilingScheme: vi.fn(() => ({ kind: 'web-mercator' })),
  };
});

import {
  UrlTemplateImageryProvider,
  WebMapTileServiceImageryProvider,
  WebMercatorTilingScheme,
} from 'cesium';

import { getBasemapById } from '../../config/basemaps';
import { createImageryProviderForBasemap, setViewerBasemap } from './cesiumBasemap';

describe('cesiumBasemap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates a WMTS imagery provider for the NASA basemap', () => {
    const basemap = getBasemapById('nasa-gibs-blue-marble');
    expect(basemap).toBeTruthy();

    createImageryProviderForBasemap(basemap!);

    expect(vi.mocked(WebMapTileServiceImageryProvider)).toHaveBeenCalledWith(
      expect.objectContaining({
        url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
        layer: 'BlueMarble_NextGeneration',
        tileMatrixSetID: 'GoogleMapsCompatible_Level8',
      }),
    );
  });

  it('normalizes TMS templates to use reverseY', () => {
    createImageryProviderForBasemap({
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

  it('replaces the viewer base layer and requests render', () => {
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

    setViewerBasemap(viewer as unknown as never, basemap!);

    expect(viewer.imageryLayers.get).toHaveBeenCalledWith(0);
    expect(viewer.imageryLayers.remove).toHaveBeenCalledWith(baseLayer, true);
    expect(viewer.imageryLayers.addImageryProvider).toHaveBeenCalledWith(
      expect.anything(),
      0,
    );
    expect(viewer.scene.requestRender).toHaveBeenCalledTimes(1);
  });
});
