import {
  Cartesian2,
  Cartesian3,
  Cartographic,
  Color,
  ColorMaterialProperty,
  ConstantPositionProperty,
  ConstantProperty,
  EllipsoidTerrainProvider,
  Entity,
  ImageryLayer,
  Math as CesiumMath,
  PolygonHierarchy,
  PropertyBag,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
} from 'cesium';
import { useEffect, useRef } from 'react';

import type { LonLat } from '../../lib/geo';

type Hazard = { id: string; vertices: LonLat[] };

type Movement = { position?: Cartesian2; endPosition?: Cartesian2 };

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

type HazardEntityMetadata =
  | { kind: 'hazardPolygon'; hazardId: string }
  | { kind: 'hazardVertex'; hazardId: string; index: number };

function createEntityProperties(metadata: HazardEntityMetadata): PropertyBag {
  return new PropertyBag(metadata);
}

function readHazardEntityMetadata(entity: Entity): HazardEntityMetadata | null {
  const raw = entity.properties?.getValue?.();
  if (!isRecord(raw)) return null;
  const kind = raw.kind;
  const hazardId = raw.hazardId;

  if (kind === 'hazardPolygon') {
    if (typeof hazardId !== 'string' || hazardId.trim().length === 0) return null;
    return { kind, hazardId };
  }

  if (kind === 'hazardVertex') {
    if (typeof hazardId !== 'string' || hazardId.trim().length === 0) return null;
    const index = raw.index;
    if (typeof index !== 'number' || !Number.isInteger(index) || index < 0) return null;
    return { kind, hazardId, index };
  }

  return null;
}

function getPickedEntity(picked: unknown): Entity | null {
  if (!isRecord(picked)) return null;
  const id = picked.id;
  if (!isRecord(id)) return null;
  return id as unknown as Entity;
}

function pickLonLat(viewer: Viewer, position: Cartesian2): LonLat | null {
  let cartesian: Cartesian3 | undefined;
  if (viewer.scene.pickPositionSupported) {
    try {
      cartesian = viewer.scene.pickPosition(position);
    } catch {
      cartesian = undefined;
    }
  }

  if (!cartesian) {
    cartesian = viewer.camera.pickEllipsoid(position, viewer.scene.globe.ellipsoid);
  }
  if (!cartesian) return null;

  const cartographic = Cartographic.fromCartesian(cartesian);
  const lon = CesiumMath.toDegrees(cartographic.longitude);
  const lat = CesiumMath.toDegrees(cartographic.latitude);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  return { lon, lat };
}

function setCameraInteractionEnabled(viewer: Viewer, enabled: boolean) {
  const controller = viewer.scene.screenSpaceCameraController;
  controller.enableRotate = enabled;
  controller.enableTranslate = enabled;
}

type EntitiesByHazardId = Map<string, { polygon: Entity; vertices: Entity[] }>;

function setConstantPropertyValue<T>(existing: unknown, value: T): ConstantProperty {
  if (existing instanceof ConstantProperty) {
    existing.setValue(value);
    return existing;
  }
  return new ConstantProperty(value);
}

function setConstantPositionValue(existing: unknown, value: Cartesian3): ConstantPositionProperty {
  if (existing instanceof ConstantPositionProperty) {
    existing.setValue(value);
    return existing;
  }
  return new ConstantPositionProperty(value);
}

function requestRender(viewer: Viewer) {
  viewer.scene.requestRender();
}

function syncHazardEntities(options: {
  viewer: Viewer;
  hazards: Hazard[];
  activeHazardId: string | null;
  entitiesByHazardId: EntitiesByHazardId;
}) {
  const { viewer, hazards, activeHazardId, entitiesByHazardId } = options;

  const activeFill = Color.CYAN.withAlpha(0.3);
  const activeOutline = Color.CYAN.withAlpha(0.95);
  const inactiveFill = Color.CYAN.withAlpha(0.12);
  const inactiveOutline = Color.CYAN.withAlpha(0.35);

  const nextIds = new Set(hazards.map((hazard) => hazard.id));
  for (const [hazardId, entry] of entitiesByHazardId.entries()) {
    if (nextIds.has(hazardId)) continue;
    viewer.entities.remove(entry.polygon);
    for (const entity of entry.vertices) viewer.entities.remove(entity);
    entitiesByHazardId.delete(hazardId);
  }

  for (const hazard of hazards) {
    const isActive = hazard.id === activeHazardId;
    const style = {
      fill: isActive ? activeFill : inactiveFill,
      outline: isActive ? activeOutline : inactiveOutline,
    };

    let entry = entitiesByHazardId.get(hazard.id);
    if (!entry) {
      const polygon = viewer.entities.add({
        id: `hazard-polygon:${hazard.id}`,
        polygon: {
          hierarchy: new ConstantProperty(new PolygonHierarchy([])),
          material: new ColorMaterialProperty(style.fill),
          outline: new ConstantProperty(true),
          outlineColor: new ConstantProperty(style.outline),
          show: new ConstantProperty(false),
        },
        properties: createEntityProperties({ kind: 'hazardPolygon', hazardId: hazard.id }),
      });
      entry = { polygon, vertices: [] };
      entitiesByHazardId.set(hazard.id, entry);
    }

    const polygonGraphics = entry.polygon.polygon;

    const positions = hazard.vertices.map((vertex) => Cartesian3.fromDegrees(vertex.lon, vertex.lat));
    if (polygonGraphics) {
      polygonGraphics.hierarchy = setConstantPropertyValue(polygonGraphics.hierarchy, new PolygonHierarchy(positions));
      polygonGraphics.material = new ColorMaterialProperty(style.fill);
      polygonGraphics.outline = setConstantPropertyValue(polygonGraphics.outline, true);
      polygonGraphics.outlineColor = setConstantPropertyValue(polygonGraphics.outlineColor, style.outline);
      polygonGraphics.show = setConstantPropertyValue(polygonGraphics.show, hazard.vertices.length >= 3);
    }

    while (entry.vertices.length < hazard.vertices.length) {
      const index = entry.vertices.length;
      const vertex = hazard.vertices[index]!;
      const entity = viewer.entities.add({
        id: `hazard-vertex:${hazard.id}:${index}`,
        position: new ConstantPositionProperty(Cartesian3.fromDegrees(vertex.lon, vertex.lat)),
        point: {
          pixelSize: 10,
          color: Color.WHITE.withAlpha(0.95),
          outlineColor: Color.BLACK.withAlpha(0.6),
          outlineWidth: 2,
        },
        show: isActive,
        properties: createEntityProperties({ kind: 'hazardVertex', hazardId: hazard.id, index }),
      });
      entry.vertices.push(entity);
    }

    while (entry.vertices.length > hazard.vertices.length) {
      const removed = entry.vertices.pop();
      if (removed) viewer.entities.remove(removed);
    }

    for (let index = 0; index < entry.vertices.length; index += 1) {
      const vertexEntity = entry.vertices[index]!;
      const vertex = hazard.vertices[index]!;
      vertexEntity.position = setConstantPositionValue(
        vertexEntity.position,
        Cartesian3.fromDegrees(vertex.lon, vertex.lat),
      );
      vertexEntity.show = isActive;
      vertexEntity.properties = createEntityProperties({ kind: 'hazardVertex', hazardId: hazard.id, index });
    }
  }
}

type Props = {
  hazards: Hazard[];
  activeHazardId: string | null;
  drawing: boolean;
  onSetActiveHazardId: (hazardId: string | null) => void;
  onChangeVertices: (hazardId: string, vertices: LonLat[]) => void;
  onDeleteVertex: (hazardId: string, vertexIndex: number) => void;
  onFinishDrawing: () => void;
};

export function HazardPolygonMap({
  hazards,
  activeHazardId,
  drawing,
  onSetActiveHazardId,
  onChangeVertices,
  onDeleteVertex,
  onFinishDrawing,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const viewerRef = useRef<Viewer | null>(null);
  const entitiesByHazardIdRef = useRef<EntitiesByHazardId>(new Map());
  const hazardsRef = useRef<Hazard[]>(hazards);
  const drawingRef = useRef<boolean>(drawing);
  const activeHazardIdRef = useRef<string | null>(activeHazardId);
  const callbacksRef = useRef({
    onSetActiveHazardId,
    onChangeVertices,
    onDeleteVertex,
    onFinishDrawing,
  });
  const draggingRef = useRef<{ hazardId: string; vertexIndex: number } | null>(null);
  const ignoreNextClickRef = useRef(false);

  useEffect(() => {
    hazardsRef.current = hazards;
  }, [hazards]);

  useEffect(() => {
    drawingRef.current = drawing;
  }, [drawing]);

  useEffect(() => {
    activeHazardIdRef.current = activeHazardId;
  }, [activeHazardId]);

  useEffect(() => {
    callbacksRef.current = { onSetActiveHazardId, onChangeVertices, onDeleteVertex, onFinishDrawing };
  }, [onChangeVertices, onDeleteVertex, onFinishDrawing, onSetActiveHazardId]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const entitiesByHazardId = entitiesByHazardIdRef.current;

    let baseLayer: ImageryLayer | false = false;
    try {
      baseLayer = new ImageryLayer(
        new UrlTemplateImageryProvider({
          url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          tilingScheme: new WebMercatorTilingScheme(),
        }),
      );
    } catch {
      // ignore imagery failures
    }

    const viewer = new Viewer(container, {
      animation: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      geocoder: false,
      homeButton: false,
      infoBox: false,
      navigationHelpButton: false,
      sceneModePicker: false,
      selectionIndicator: false,
      timeline: false,
      baseLayer,
      terrainProvider: new EllipsoidTerrainProvider(),
      requestRenderMode: true,
      maximumRenderTimeChange: 0,
    });
    viewerRef.current = viewer;

    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(116.391, 39.9075, 20_000_000),
    });
    requestRender(viewer);

    const preventContextMenu = (event: MouseEvent) => event.preventDefault();
    viewer.canvas.addEventListener('contextmenu', preventContextMenu);

    const pickHazardVertex = (position: Cartesian2): { hazardId: string; index: number } | null => {
      const pickedObject = viewer.scene.pick(position) as unknown;
      const entity = getPickedEntity(pickedObject);
      if (!entity) return null;
      const metadata = readHazardEntityMetadata(entity);
      if (!metadata || metadata.kind !== 'hazardVertex') return null;
      return { hazardId: metadata.hazardId, index: metadata.index };
    };

    const pickHazardPolygon = (position: Cartesian2): string | null => {
      const pickedObject = viewer.scene.pick(position) as unknown;
      const entity = getPickedEntity(pickedObject);
      if (!entity) return null;
      const metadata = readHazardEntityMetadata(entity);
      if (!metadata) return null;
      return metadata.hazardId;
    };

    const onLeftDown = (movement: Movement) => {
      const position = movement.position;
      if (!position) return;

      const activeId = activeHazardIdRef.current;
      const picked = pickHazardVertex(position);
      if (!activeId || !picked || picked.hazardId !== activeId) return;
      draggingRef.current = { hazardId: picked.hazardId, vertexIndex: picked.index };
      ignoreNextClickRef.current = true;
      setCameraInteractionEnabled(viewer, false);
    };

    const onMouseMove = (movement: Movement) => {
      const drag = draggingRef.current;
      if (!drag) return;

      const position = movement.endPosition;
      if (!position) return;

      const nextPoint = pickLonLat(viewer, position);
      if (!nextPoint) return;

      const hazards = hazardsRef.current;
      const hazard = hazards.find((entry) => entry.id === drag.hazardId);
      if (!hazard) return;

      const nextVertices = hazard.vertices.map((vertex, index) =>
        index === drag.vertexIndex ? nextPoint : vertex,
      );
      callbacksRef.current.onChangeVertices(drag.hazardId, nextVertices);
    };

    const onLeftUp = () => {
      if (!draggingRef.current) return;
      draggingRef.current = null;
      setCameraInteractionEnabled(viewer, true);
    };

    const onRightClick = (movement: Movement) => {
      const position = movement.position;
      if (!position) return;
      const picked = pickHazardVertex(position);
      if (!picked) return;
      callbacksRef.current.onDeleteVertex(picked.hazardId, picked.index);
    };

    const onLeftClick = (movement: Movement) => {
      const position = movement.position;
      if (!position) return;

      if (ignoreNextClickRef.current) {
        ignoreNextClickRef.current = false;
        return;
      }

      const hazardId = activeHazardIdRef.current;
      const isDrawing = drawingRef.current;

      if (!isDrawing) {
        const pickedHazardId = pickHazardPolygon(position);
        if (pickedHazardId) callbacksRef.current.onSetActiveHazardId(pickedHazardId);
        return;
      }

      if (!hazardId) return;

      const picked = pickLonLat(viewer, position);
      if (!picked) return;

      const hazard = hazardsRef.current.find((entry) => entry.id === hazardId);
      if (!hazard) return;

      callbacksRef.current.onChangeVertices(hazardId, [...hazard.vertices, picked]);
    };

    const onDoubleClick = () => {
      if (!drawingRef.current) return;
      callbacksRef.current.onFinishDrawing();
    };

    viewer.screenSpaceEventHandler.setInputAction(onLeftDown, ScreenSpaceEventType.LEFT_DOWN);
    viewer.screenSpaceEventHandler.setInputAction(onLeftUp, ScreenSpaceEventType.LEFT_UP);
    viewer.screenSpaceEventHandler.setInputAction(onMouseMove, ScreenSpaceEventType.MOUSE_MOVE);
    viewer.screenSpaceEventHandler.setInputAction(onLeftClick, ScreenSpaceEventType.LEFT_CLICK);
    viewer.screenSpaceEventHandler.setInputAction(onDoubleClick, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    viewer.screenSpaceEventHandler.setInputAction(onRightClick, ScreenSpaceEventType.RIGHT_CLICK);

    const observer = new ResizeObserver(() => {
      viewer.resize();
      requestRender(viewer);
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      viewer.canvas.removeEventListener('contextmenu', preventContextMenu);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOWN);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_UP);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.MOUSE_MOVE);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_CLICK);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
      viewer.screenSpaceEventHandler.removeInputAction(ScreenSpaceEventType.RIGHT_CLICK);
      viewerRef.current = null;
      entitiesByHazardId.clear();
      viewer.destroy();
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    syncHazardEntities({
      viewer,
      hazards,
      activeHazardId,
      entitiesByHazardId: entitiesByHazardIdRef.current,
    });
    requestRender(viewer);
  }, [activeHazardId, hazards]);

  return (
    <div className="w-full overflow-hidden rounded-lg border border-slate-400/20 bg-slate-950/20">
      <div ref={containerRef} className="h-72 w-full" data-testid="hazard-polygon-map" />
    </div>
  );
}
