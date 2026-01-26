import {
  Color,
  EllipsoidSurfaceAppearance,
  GeometryInstance,
  Material,
  Primitive,
  Rectangle,
  RectangleGeometry,
  type PrimitiveCollection,
  type Viewer,
} from 'cesium';

import type { LayerConfig } from '../../state/layerManager';
import { buildCloudTileUrlTemplate } from './layersApi';

const DEFAULT_LOCAL_CLOUD_TILE_ZOOM = 6;
const DEFAULT_LOCAL_CLOUD_TILE_RADIUS = 1;

const LOCAL_CLOUD_TILE_HUMAN_MATERIAL_TYPE = 'LocalCloudTileHuman';
const LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_START = 0.0;
const LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_WIDTH = 0.08;
const LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MIN_ALPHA = 0.2;
const LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MAX_ALPHA = 0.7;

let humanCloudTileMaterialRegistered = false;

function ensureHumanCloudTileMaterialRegistered(): void {
  if (humanCloudTileMaterialRegistered) return;
  humanCloudTileMaterialRegistered = true;

  const cache = (
    Material as unknown as {
      _materialCache?: {
        addMaterial?: (type: string, material: unknown) => void;
      };
    }
  )._materialCache;

  cache?.addMaterial?.(LOCAL_CLOUD_TILE_HUMAN_MATERIAL_TYPE, {
    fabric: {
      type: LOCAL_CLOUD_TILE_HUMAN_MATERIAL_TYPE,
      uniforms: {
        image: undefined,
        color: Color.WHITE,
        edgeFadeStart: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_START,
        edgeFadeWidth: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_WIDTH,
        edgeFadeMinAlpha: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MIN_ALPHA,
        edgeFadeMaxAlpha: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MAX_ALPHA,
      },
      source: `
uniform sampler2D image;
uniform vec4 color;
uniform float edgeFadeStart;
uniform float edgeFadeWidth;
uniform float edgeFadeMinAlpha;
uniform float edgeFadeMaxAlpha;

czm_material czm_getMaterial(czm_materialInput materialInput)
{
  czm_material material = czm_getDefaultMaterial(materialInput);
  vec2 st = materialInput.st;
  vec4 texel = czm_texture2D(image, st);

  float coverage = texel.a;
  if (coverage > 0.999)
  {
    coverage = max(max(texel.r, texel.g), texel.b);
  }

  float distToEdge = min(min(st.x, 1.0 - st.x), min(st.y, 1.0 - st.y));
  float edgeFactor = smoothstep(edgeFadeStart, edgeFadeStart + edgeFadeWidth, distToEdge);
  float fadedCoverage = coverage * edgeFactor;
  float keepCoverage = smoothstep(edgeFadeMinAlpha, edgeFadeMaxAlpha, coverage);
  float finalCoverage = mix(fadedCoverage, coverage, keepCoverage);

  material.diffuse = texel.rgb * color.rgb;
  material.alpha = finalCoverage * color.a;
  return material;
}
`,
    },
    translucent: () => true,
  });
}

function createCloudTileImage(options: { url: string; requestRender: () => void }): HTMLImageElement | string {
  if (typeof Image !== 'function') return options.url;
  const image = new Image();
  image.crossOrigin = 'anonymous';
  const requestRender = () => {
    try {
      options.requestRender();
    } catch {
      // ignore render requests during teardown
    }
  };
  image.onload = requestRender;
  image.onerror = requestRender;
  image.src = options.url;
  return image;
}

type LocalCloudTileSettings = {
  zoom: number;
  radius: number;
};

type TileBoundsDegrees = {
  west: number;
  south: number;
  east: number;
  north: number;
};

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function clamp01(value: number): number {
  return clamp(value, 0, 1);
}

function tilesAtZoom(zoom: number): number {
  if (!Number.isFinite(zoom) || zoom < 0) return 1;
  return 2 ** Math.floor(zoom);
}

function getViewerCameraHeightMeters(viewer: Viewer): number | null {
  const camera = viewer.camera as unknown as { positionCartographic?: { height?: number } } | undefined;
  const height = camera?.positionCartographic?.height;
  if (typeof height !== 'number' || !Number.isFinite(height)) return null;
  return height;
}

function localCloudTileSettingsForHeightAboveSurface(heightMeters: number | null): LocalCloudTileSettings {
  if (heightMeters == null) {
    return {
      zoom: DEFAULT_LOCAL_CLOUD_TILE_ZOOM,
      radius: DEFAULT_LOCAL_CLOUD_TILE_RADIUS,
    };
  }

  if (heightMeters <= 2_500) {
    return { zoom: 10, radius: 2 };
  }

  if (heightMeters <= 10_000) {
    return { zoom: 9, radius: 2 };
  }

  if (heightMeters <= 40_000) {
    return { zoom: 8, radius: 1 };
  }

  if (heightMeters <= 150_000) {
    return { zoom: 7, radius: 1 };
  }

  return {
    zoom: DEFAULT_LOCAL_CLOUD_TILE_ZOOM,
    radius: DEFAULT_LOCAL_CLOUD_TILE_RADIUS,
  };
}

function tileXYForLonLatDegrees(options: { lon: number; lat: number; zoom: number }): { x: number; y: number } {
  const zoom = Math.max(0, Math.floor(options.zoom));
  const lon = clamp(options.lon, -180, 180);
  const lat = clamp(options.lat, -90, 90);
  const n = tilesAtZoom(zoom);
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((90 - lat) / 180) * n);
  return {
    x: clamp(x, 0, n - 1),
    y: clamp(y, 0, n - 1),
  };
}

function tileBoundsForXY(options: { x: number; y: number; zoom: number }): TileBoundsDegrees {
  const zoom = Math.max(0, Math.floor(options.zoom));
  const n = tilesAtZoom(zoom);
  const tileWidth = 360 / n;
  const tileHeight = 180 / n;
  const west = -180 + options.x * tileWidth;
  const east = west + tileWidth;
  const north = 90 - options.y * tileHeight;
  const south = north - tileHeight;
  return { west, south, east, north };
}

function fillUrlTemplate(urlTemplate: string, params: { z: number; x: number; y: number }): string {
  return urlTemplate
    .replaceAll('{z}', String(params.z))
    .replaceAll('{x}', String(params.x))
    .replaceAll('{y}', String(params.y));
}

function normalizeCloudTileVariable(variable: string): 'tcc' | 'humidity' {
  const normalized = variable.trim().toLowerCase();
  if (normalized === 'humidity' || normalized === 'r' || normalized === 'rh') return 'humidity';
  return 'tcc';
}

function cloudLayerHeightOffsetMeters(layer: Pick<LayerConfig, 'variable' | 'level'>): number {
  const variable = normalizeCloudTileVariable(layer.variable);
  if (variable === 'tcc') return 4500;

  const level = layer.level;
  if (typeof level !== 'number' || !Number.isFinite(level)) return 4500;

  const rounded = Math.round(level);
  switch (rounded) {
    case 850:
      return 1800;
    case 700:
      return 3200;
    case 500:
      return 5600;
    case 300:
      return 9000;
    default:
      if (rounded >= 850) return 1800;
      if (rounded >= 700) return 3200;
      if (rounded >= 500) return 5600;
      return 9000;
  }
}

type PrimitiveRecord = {
  primitive: Primitive;
  material: Material;
};

type CloudGroup = {
  key: string;
  records: PrimitiveRecord[];
};

export type LocalCloudStackUpdate = {
  enabled: boolean;
  humanModeEnabled: boolean;
  apiBaseUrl: string | null;
  timeKey: string | null;
  lon: number;
  lat: number;
  surfaceHeightMeters: number;
  layers: LayerConfig[];
};

export class LocalCloudStack {
  private viewer: Viewer | null;
  private primitives: PrimitiveCollection | null;
  private groups = new Map<string, CloudGroup>();

  constructor(viewer: Viewer | null | undefined) {
    this.viewer = viewer ?? null;
    const scenePrimitives = (viewer as unknown as { scene?: { primitives?: unknown } } | null)?.scene?.primitives;
    this.primitives = scenePrimitives ? (scenePrimitives as PrimitiveCollection) : null;
  }

  private requestRender(): void {
    const scene = (this.viewer as unknown as { scene?: { requestRender?: () => void } } | null)?.scene;
    try {
      scene?.requestRender?.();
    } catch {
      // ignore render requests during teardown
    }
  }

  private removePrimitive(primitive: Primitive): void {
    if (!this.primitives) return;
    try {
      this.primitives.remove(primitive);
    } catch {
      // ignore teardown errors
    }
  }

  update(update: LocalCloudStackUpdate): void {
    const viewer = this.viewer;
    const primitives = this.primitives;
    if (!viewer || !primitives) {
      this.clear();
      return;
    }
    if (!update.enabled) {
      this.clear();
      return;
    }
    if (update.humanModeEnabled) {
      ensureHumanCloudTileMaterialRegistered();
    }
    const apiBaseUrl = update.apiBaseUrl?.trim() ?? '';
    const timeKey = update.timeKey?.trim() ?? '';
    if (!apiBaseUrl || !timeKey) {
      this.clear();
      return;
    }
    if (!Number.isFinite(update.lon) || !Number.isFinite(update.lat)) {
      this.clear();
      return;
    }

    const layers = update.layers.filter((layer) => layer.type === 'cloud' && layer.visible && layer.opacity > 0);
    if (layers.length === 0) {
      this.clear();
      return;
    }

    const cameraHeightMeters = getViewerCameraHeightMeters(viewer);
    const heightAboveSurfaceMeters =
      cameraHeightMeters == null
        ? null
        : Math.max(0, cameraHeightMeters - Math.max(0, update.surfaceHeightMeters));

    const { zoom, radius } = localCloudTileSettingsForHeightAboveSurface(heightAboveSurfaceMeters);
    const center = tileXYForLonLatDegrees({ lon: update.lon, lat: update.lat, zoom });
    const tiles = tilesAtZoom(zoom);

    const nextGroupIds = new Set<string>();

    for (const layer of layers) {
      nextGroupIds.add(layer.id);

      const variable = normalizeCloudTileVariable(layer.variable);
      const levelKey =
        variable === 'humidity' && typeof layer.level === 'number' && Number.isFinite(layer.level)
          ? String(Math.round(layer.level))
          : undefined;
      const heightMeters = Math.max(0, update.surfaceHeightMeters + cloudLayerHeightOffsetMeters(layer));
      const alpha = clamp01(layer.opacity);

      const key = `${timeKey}:${variable}:${levelKey ?? 'sfc'}:${heightMeters}:${center.x}:${center.y}:${zoom}:${radius}:${
        update.humanModeEnabled ? 'human' : 'default'
      }`;
      const existing = this.groups.get(layer.id);

      if (!existing || existing.key !== key) {
        existing?.records.forEach((record) => this.removePrimitive(record.primitive));
        const records: PrimitiveRecord[] = [];

        const template = buildCloudTileUrlTemplate({
          apiBaseUrl,
          timeKey,
          variable,
          ...(levelKey ? { level: levelKey } : {}),
        });

        for (let dy = -radius; dy <= radius; dy += 1) {
          const y = clamp(center.y + dy, 0, tiles - 1);
          for (let dx = -radius; dx <= radius; dx += 1) {
            const x = (center.x + dx + tiles) % tiles;
            const bounds = tileBoundsForXY({ x, y, zoom });
            const rectangle = Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north);
            const geometry = new RectangleGeometry({
              rectangle,
              height: heightMeters,
              vertexFormat: EllipsoidSurfaceAppearance.VERTEX_FORMAT,
            });

            const requestRender = () => this.requestRender();
            const image = createCloudTileImage({
              url: fillUrlTemplate(template, { z: zoom, x, y }),
              requestRender,
            });
            const material = update.humanModeEnabled
              ? Material.fromType(LOCAL_CLOUD_TILE_HUMAN_MATERIAL_TYPE, {
                  image,
                  color: Color.WHITE.withAlpha(alpha),
                  edgeFadeStart: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_START,
                  edgeFadeWidth: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_WIDTH,
                  edgeFadeMinAlpha: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MIN_ALPHA,
                  edgeFadeMaxAlpha: LOCAL_CLOUD_TILE_HUMAN_EDGE_FADE_MAX_ALPHA,
                })
              : Material.fromType('Image', {
                  image,
                  transparent: true,
                  color: Color.WHITE.withAlpha(alpha),
                });

            const appearance = new EllipsoidSurfaceAppearance({
              aboveGround: false,
              translucent: true,
              faceForward: true,
              material,
              renderState: { cull: { enabled: false } },
            });

            const primitive = new Primitive({
              geometryInstances: new GeometryInstance({ geometry }),
              appearance,
              asynchronous: false,
              show: true,
            });

            primitives.add(primitive);
            records.push({ primitive, material });
          }
        }

        this.groups.set(layer.id, { key, records });
      } else {
        for (const record of existing.records) {
          const uniforms = record.material.uniforms as unknown as { color?: unknown } | undefined;
          if (uniforms) uniforms.color = Color.WHITE.withAlpha(alpha);
          record.primitive.show = true;
        }
      }
    }

    for (const [id, group] of this.groups.entries()) {
      if (nextGroupIds.has(id)) continue;
      for (const record of group.records) this.removePrimitive(record.primitive);
      this.groups.delete(id);
    }

    this.requestRender();
  }

  destroy(): void {
    this.clear();
    this.viewer = null;
    this.primitives = null;
  }

  private clear(): void {
    if (this.groups.size === 0) return;
    for (const group of this.groups.values()) {
      for (const record of group.records) {
        this.removePrimitive(record.primitive);
      }
    }
    this.groups.clear();
    this.requestRender();
  }
}
