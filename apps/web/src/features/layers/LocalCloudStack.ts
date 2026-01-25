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

const LOCAL_CLOUD_TILE_ZOOM = 6;
const LOCAL_CLOUD_TILE_RADIUS = 1;

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
  apiBaseUrl: string | null;
  timeKey: string | null;
  lon: number;
  lat: number;
  surfaceHeightMeters: number;
  layers: LayerConfig[];
};

export class LocalCloudStack {
  private readonly viewer: Viewer;
  private readonly primitives: PrimitiveCollection;
  private groups = new Map<string, CloudGroup>();

  constructor(viewer: Viewer) {
    this.viewer = viewer;
    this.primitives = viewer.scene.primitives as unknown as PrimitiveCollection;
  }

  update(update: LocalCloudStackUpdate): void {
    if (!update.enabled) {
      this.clear();
      return;
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

    const zoom = LOCAL_CLOUD_TILE_ZOOM;
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

      const key = `${timeKey}:${variable}:${levelKey ?? 'sfc'}:${heightMeters}:${center.x}:${center.y}:${zoom}`;
      const existing = this.groups.get(layer.id);

      if (!existing || existing.key !== key) {
        existing?.records.forEach((record) => this.primitives.remove(record.primitive));
        const records: PrimitiveRecord[] = [];

        const template = buildCloudTileUrlTemplate({
          apiBaseUrl,
          timeKey,
          variable,
          ...(levelKey ? { level: levelKey } : {}),
        });

        for (let dy = -LOCAL_CLOUD_TILE_RADIUS; dy <= LOCAL_CLOUD_TILE_RADIUS; dy += 1) {
          const y = clamp(center.y + dy, 0, tiles - 1);
          for (let dx = -LOCAL_CLOUD_TILE_RADIUS; dx <= LOCAL_CLOUD_TILE_RADIUS; dx += 1) {
            const x = (center.x + dx + tiles) % tiles;
            const bounds = tileBoundsForXY({ x, y, zoom });
            const rectangle = Rectangle.fromDegrees(bounds.west, bounds.south, bounds.east, bounds.north);
            const geometry = new RectangleGeometry({
              rectangle,
              height: heightMeters,
              vertexFormat: EllipsoidSurfaceAppearance.VERTEX_FORMAT,
            });

            const material = Material.fromType('Image', {
              image: fillUrlTemplate(template, { z: zoom, x, y }),
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

            this.primitives.add(primitive);
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
      for (const record of group.records) this.primitives.remove(record.primitive);
      this.groups.delete(id);
    }

    this.viewer.scene.requestRender();
  }

  destroy(): void {
    this.clear();
  }

  private clear(): void {
    if (this.groups.size === 0) return;
    for (const group of this.groups.values()) {
      for (const record of group.records) {
        this.primitives.remove(record.primitive);
      }
    }
    this.groups.clear();
    this.viewer.scene.requestRender();
  }
}

