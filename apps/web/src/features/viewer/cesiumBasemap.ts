import {
  UrlTemplateImageryProvider,
  WebMapTileServiceImageryProvider,
  WebMercatorTilingScheme,
  type ImageryProvider,
  type Viewer,
} from 'cesium';

import { type BasemapConfig, type UrlTemplateBasemap } from '../../config/basemaps';

function toCesiumUrlTemplate(basemap: UrlTemplateBasemap): string {
  if (basemap.scheme === 'xyz') return basemap.urlTemplate;
  if (basemap.urlTemplate.includes('{reverseY}')) return basemap.urlTemplate;
  return basemap.urlTemplate.replaceAll('{y}', '{reverseY}');
}

export function createImageryProviderForBasemap(basemap: BasemapConfig): ImageryProvider {
  if (basemap.kind === 'wmts') {
    return new WebMapTileServiceImageryProvider({
      url: basemap.url,
      layer: basemap.layer,
      style: basemap.style,
      format: basemap.format,
      tileMatrixSetID: basemap.tileMatrixSetID,
      maximumLevel: basemap.maximumLevel,
      credit: basemap.credit,
    });
  }

  return new UrlTemplateImageryProvider({
    url: toCesiumUrlTemplate(basemap),
    tilingScheme: new WebMercatorTilingScheme(),
    maximumLevel: basemap.maximumLevel,
    credit: basemap.credit,
  });
}

export function setViewerBasemap(viewer: Viewer, basemap: BasemapConfig): void {
  const baseLayer = viewer.imageryLayers.get(0);
  if (baseLayer) {
    viewer.imageryLayers.remove(baseLayer, true);
  }

  const provider = createImageryProviderForBasemap(basemap);
  viewer.imageryLayers.addImageryProvider(provider, 0);
  viewer.scene.requestRender();
}

