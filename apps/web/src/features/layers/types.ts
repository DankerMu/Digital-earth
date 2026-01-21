export type CldasTileUrlTemplateOptions = {
  apiBaseUrl: string;
  timeKey: string;
  variable: string;
};

export type TemperatureLayerParams = CldasTileUrlTemplateOptions & {
  id: string;
  opacity: number;
  visible: boolean;
  zIndex: number;
};

export type CloudLayerParams = CldasTileUrlTemplateOptions & {
  id: string;
  opacity: number;
  visible: boolean;
  zIndex: number;
};

export type PrecipitationLayerParams = Omit<CldasTileUrlTemplateOptions, 'variable'> & {
  id: string;
  opacity: number;
  visible: boolean;
  zIndex: number;
  threshold?: number | null;
};

export type WindLayerParams = Omit<CldasTileUrlTemplateOptions, 'variable'> & {
  id: string;
  opacity: number;
  visible: boolean;
  zIndex: number;
  density: number;
  maxArrows?: number;
};
