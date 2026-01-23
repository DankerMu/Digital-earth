import {
  IonWorldImageryStyle,
  UrlTemplateImageryProvider,
  WebMapTileServiceImageryProvider,
  WebMercatorTilingScheme,
  createWorldImageryAsync,
  type ImageryProvider,
  type Viewer,
} from 'cesium';

import { type BasemapConfig, type IonBasemap, type UrlTemplateBasemap, type WmtsBasemap } from '../../config/basemaps';

function toCesiumUrlTemplate(basemap: UrlTemplateBasemap): string {
  if (basemap.scheme === 'xyz') return basemap.urlTemplate;
  if (basemap.urlTemplate.includes('{reverseY}')) return basemap.urlTemplate;
  return basemap.urlTemplate.replaceAll('{y}', '{reverseY}');
}

function toIonWorldImageryStyle(style: IonBasemap['style']): IonWorldImageryStyle | undefined {
  if (style === 'aerial') return IonWorldImageryStyle.AERIAL;
  if (style === 'aerial-with-labels') return IonWorldImageryStyle.AERIAL_WITH_LABELS;
  if (style === 'road') return IonWorldImageryStyle.ROAD;
  return undefined;
}

export function createImageryProviderForBasemap(basemap: WmtsBasemap | UrlTemplateBasemap): ImageryProvider {
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

export async function createImageryProviderForBasemapAsync(
  basemap: BasemapConfig,
): Promise<ImageryProvider> {
  if (basemap.kind === 'ion') {
    const style = toIonWorldImageryStyle(basemap.style);
    return createWorldImageryAsync(style ? { style } : undefined);
  }

  return createImageryProviderForBasemap(basemap);
}

export function setViewerImageryProvider(viewer: Viewer, provider: ImageryProvider): void {
  const baseLayer = viewer.imageryLayers.get(0);
  if (baseLayer) {
    viewer.imageryLayers.remove(baseLayer, true);
  }

  viewer.imageryLayers.addImageryProvider(provider, 0);
  viewer.scene.requestRender();
}

export async function setViewerBasemap(viewer: Viewer, basemap: BasemapConfig): Promise<boolean> {
  try {
    const provider = await createImageryProviderForBasemapAsync(basemap);
    setViewerImageryProvider(viewer, provider);
    return true;
  } catch (error: unknown) {
    console.warn('[Digital Earth] failed to set basemap', { basemapId: basemap.id, error });
    return false;
  }
}
