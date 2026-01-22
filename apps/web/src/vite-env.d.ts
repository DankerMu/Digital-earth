/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_E2E?: string;
}

interface Window {
  __DIGITAL_EARTH_E2E__?: {
    getEventEntityIds?: () => string[];
    getRiskPoiIds?: () => number[];
    getRiskPoiCanvasPosition?: (poiId: number) => { x: number; y: number } | null;
    isLayerGlobalShellActive?: () => boolean;
  };
}
