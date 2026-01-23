export type BasemapConfig = {
  kind: 'wmts';
  id: string;
  label: string;
  description?: string;
  credit: string;
  url: string;
  layer: string;
  style: string;
  format: string;
  tileMatrixSetID: string;
  maximumLevel?: number;
} | {
  kind: 'url-template';
  id: string;
  label: string;
  description?: string;
  credit: string;
  urlTemplate: string;
  maximumLevel?: number;
  scheme: 'xyz' | 'tms';
} | {
  kind: 'ion';
  id: string;
  label: string;
  description?: string;
  credit: string;
  style?: 'aerial' | 'aerial-with-labels' | 'road';
};

export const BASEMAPS = [
  {
    kind: 'ion',
    id: 'ion-world-imagery',
    label: 'Bing Maps (Cesium ion)',
    description: 'Cesium Ion World Imagery（asset 2，需要 Ion token）',
    credit: 'Cesium ion / Bing Maps',
    style: 'aerial-with-labels',
  },
  {
    kind: 'wmts',
    id: 'nasa-gibs-blue-marble',
    label: 'NASA GIBS (Blue Marble)',
    description: 'Blue Marble Next Generation（静态）',
    credit: 'NASA GIBS',
    url: 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi',
    layer: 'BlueMarble_NextGeneration',
    style: 'default',
    format: 'image/jpeg',
    tileMatrixSetID: 'GoogleMapsCompatible_Level8',
    maximumLevel: 8,
  },
  {
    kind: 'url-template',
    id: 's2cloudless-2021',
    label: 'Sentinel-2 Cloudless (EOX)',
    description: '高分辨率（EOX 公共瓦片服务）',
    credit: 'EOX / Sentinel-2 cloudless',
    urlTemplate:
      'https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg',
    scheme: 'xyz',
    maximumLevel: 14,
  },
] as const satisfies readonly BasemapConfig[];

export type BasemapId = (typeof BASEMAPS)[number]['id'];

export const DEFAULT_BASEMAP_ID: BasemapId = 's2cloudless-2021';

export type WmtsBasemap = Extract<BasemapConfig, { kind: 'wmts' }>;
export type UrlTemplateBasemap = Extract<BasemapConfig, { kind: 'url-template' }>;
export type IonBasemap = Extract<BasemapConfig, { kind: 'ion' }>;

export function isBasemapId(value: string): value is BasemapId {
  return BASEMAPS.some((basemap) => basemap.id === value);
}

export function getBasemapById(id: BasemapId | string): BasemapConfig | undefined {
  return BASEMAPS.find((basemap) => basemap.id === id);
}
