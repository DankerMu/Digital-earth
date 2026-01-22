import {
  Cartesian3,
  Cartographic,
  Color,
  EllipsoidTerrainProvider,
  Math as CesiumMath,
  PolygonHierarchy,
  ScreenSpaceEventType,
  UrlTemplateImageryProvider,
  Viewer,
  WebMercatorTilingScheme,
} from 'cesium';
import { useEffect, useRef } from 'react';

import type { LonLat } from '../../lib/geo';

type Hazard = { id: string; vertices: LonLat[] };

type Movement = { position?: unknown; endPosition?: unknown };

type PickResult = { id?: unknown };

type HazardPolygonEntity = { __hazardPolygon?: { hazardId: string } };
type HazardVertexEntity = { __hazardVertex?: { hazardId: string; index: number } };

function pickEntity(picked: unknown): (HazardPolygonEntity & HazardVertexEntity) | null {
  if (!picked || typeof picked !== 'object') return null;
  const id = (picked as PickResult).id;
  if (!id || typeof id !== 'object') return null;
  return id as HazardPolygonEntity & HazardVertexEntity;
}

function pickLonLat(viewer: Viewer, position: unknown): LonLat | null {
  const cartesian =
    (viewer.scene as unknown as { pickPosition?: (pos: unknown) => unknown }).pickPosition?.(position) ??
    (viewer.camera as unknown as { pickEllipsoid?: (pos: unknown, ellipsoid?: unknown) => unknown }).pickEllipsoid?.(
      position,
      (viewer.scene as unknown as { globe?: { ellipsoid?: unknown } }).globe?.ellipsoid,
    );

  if (!cartesian) return null;

  const cartographic = Cartographic.fromCartesian(cartesian as never) as Cartographic;
  const lon = CesiumMath.toDegrees(cartographic.longitude);
  const lat = CesiumMath.toDegrees(cartographic.latitude);
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null;
  return { lon, lat };
}

function setCameraInteractionEnabled(viewer: Viewer, enabled: boolean) {
  const controller = viewer.scene.screenSpaceCameraController as unknown as {
    enableRotate?: boolean;
    enableTranslate?: boolean;
  };
  if (typeof controller.enableRotate === 'boolean') controller.enableRotate = enabled;
  if (typeof controller.enableTranslate === 'boolean') controller.enableTranslate = enabled;
}

type EntitiesByHazardId = Map<
  string,
  {
    polygon: unknown;
    vertices: unknown[];
  }
>;

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
    (viewer.entities as unknown as { remove?: (entity: unknown) => void }).remove?.(entry.polygon);
    for (const entity of entry.vertices) {
      (viewer.entities as unknown as { remove?: (entity: unknown) => void }).remove?.(entity);
    }
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
          hierarchy: new PolygonHierarchy([]),
          material: style.fill,
          outline: true,
          outlineColor: style.outline,
        },
      });
      (polygon as unknown as HazardPolygonEntity).__hazardPolygon = { hazardId: hazard.id };
      entry = { polygon, vertices: [] };
      entitiesByHazardId.set(hazard.id, entry);
    }

    const polygonGraphics = (entry.polygon as { polygon?: unknown }).polygon as
      | {
          hierarchy?: unknown;
          material?: unknown;
          outline?: unknown;
          outlineColor?: unknown;
          show?: unknown;
        }
      | undefined;

    const positions = hazard.vertices.map((vertex) => Cartesian3.fromDegrees(vertex.lon, vertex.lat));
    if (polygonGraphics) {
      polygonGraphics.hierarchy = new PolygonHierarchy(positions);
      polygonGraphics.material = style.fill;
      polygonGraphics.outline = true;
      polygonGraphics.outlineColor = style.outline;
      polygonGraphics.show = hazard.vertices.length >= 3;
    }

    while (entry.vertices.length < hazard.vertices.length) {
      const index = entry.vertices.length;
      const vertex = hazard.vertices[index] ?? { lon: 0, lat: 0 };
      const entity = viewer.entities.add({
        id: `hazard-vertex:${hazard.id}:${index}`,
        position: Cartesian3.fromDegrees(vertex.lon, vertex.lat),
        point: {
          pixelSize: 10,
          color: Color.WHITE.withAlpha(0.95),
          outlineColor: Color.BLACK.withAlpha(0.6),
          outlineWidth: 2,
        },
        show: isActive,
      });
      (entity as unknown as HazardVertexEntity).__hazardVertex = { hazardId: hazard.id, index };
      entry.vertices.push(entity);
    }

    while (entry.vertices.length > hazard.vertices.length) {
      const removed = entry.vertices.pop();
      if (removed) (viewer.entities as unknown as { remove?: (entity: unknown) => void }).remove?.(removed);
    }

    for (let index = 0; index < entry.vertices.length; index += 1) {
      const vertexEntity = entry.vertices[index] as {
        position?: unknown;
        show?: unknown;
        __hazardVertex?: { hazardId: string; index: number };
      };
      const vertex = hazard.vertices[index]!;
      vertexEntity.position = Cartesian3.fromDegrees(vertex.lon, vertex.lat);
      vertexEntity.show = isActive;
      if (vertexEntity.__hazardVertex) {
        vertexEntity.__hazardVertex.hazardId = hazard.id;
        vertexEntity.__hazardVertex.index = index;
      } else {
        vertexEntity.__hazardVertex = { hazardId: hazard.id, index };
      }
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
      terrainProvider: new EllipsoidTerrainProvider(),
    });
    viewerRef.current = viewer;

    try {
      viewer.imageryLayers.addImageryProvider(
        new UrlTemplateImageryProvider({
          url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
          tilingScheme: new WebMercatorTilingScheme(),
        }),
      );
    } catch {
      // ignore imagery failures
    }

    viewer.camera.setView({
      destination: Cartesian3.fromDegrees(116.391, 39.9075, 20_000_000),
    });

    const handler = viewer.screenSpaceEventHandler as unknown as {
      setInputAction?: (cb: (movement: Movement) => void, type: unknown) => void;
      removeInputAction?: (type: unknown) => void;
    };

    const pickHazardVertex = (position: unknown): { hazardId: string; index: number } | null => {
      const pickedObject = (viewer.scene as unknown as { pick?: (pos: unknown) => unknown }).pick?.(position);
      const entity = pickEntity(pickedObject);
      const metadata = entity?.__hazardVertex;
      if (!metadata) return null;
      return { hazardId: metadata.hazardId, index: metadata.index };
    };

    const pickHazardPolygon = (position: unknown): string | null => {
      const pickedObject = (viewer.scene as unknown as { pick?: (pos: unknown) => unknown }).pick?.(position);
      const entity = pickEntity(pickedObject);
      return entity?.__hazardPolygon?.hazardId ?? entity?.__hazardVertex?.hazardId ?? null;
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

    handler.setInputAction?.(onLeftDown, ScreenSpaceEventType.LEFT_DOWN);
    handler.setInputAction?.(onLeftUp, ScreenSpaceEventType.LEFT_UP);
    handler.setInputAction?.(onMouseMove, ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction?.(onLeftClick, ScreenSpaceEventType.LEFT_CLICK);
    handler.setInputAction?.(onDoubleClick, ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    handler.setInputAction?.(onRightClick, ScreenSpaceEventType.RIGHT_CLICK);

    const observer = new ResizeObserver(() => viewer.resize());
    observer.observe(container);

    return () => {
      observer.disconnect();
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_DOWN);
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_UP);
      handler.removeInputAction?.(ScreenSpaceEventType.MOUSE_MOVE);
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_CLICK);
      handler.removeInputAction?.(ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
      handler.removeInputAction?.(ScreenSpaceEventType.RIGHT_CLICK);
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
  }, [activeHazardId, hazards]);

  return (
    <div className="w-full overflow-hidden rounded-lg border border-slate-400/20 bg-slate-950/20">
      <div ref={containerRef} className="h-72 w-full" data-testid="hazard-polygon-map" />
    </div>
  );
}
