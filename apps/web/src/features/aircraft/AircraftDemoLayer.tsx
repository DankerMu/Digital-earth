import { Cartesian3, CustomDataSource, Entity, type Viewer } from 'cesium';
import { useEffect, useRef } from 'react';

import type { CameraPerspectiveId } from '../../state/cameraPerspective';
import { useAircraftDemoStore } from '../../state/aircraftDemo';
import type { ViewModeRoute } from '../../state/viewMode';

type AircraftDemoLayerProps = {
  viewer: Viewer;
  viewModeRoute: ViewModeRoute;
  cameraPerspectiveId: CameraPerspectiveId;
};

type AircraftDemoPoint = {
  id: string;
  eastMeters: number;
  northMeters: number;
  altitudeMeters: number;
};

const METERS_PER_DEGREE_LAT = 111_320;

const AIRCRAFT_POINTS: AircraftDemoPoint[] = [
  { id: 'alpha', eastMeters: 0, northMeters: 0, altitudeMeters: 10_000 },
  { id: 'bravo', eastMeters: 4500, northMeters: 1500, altitudeMeters: 9_200 },
  { id: 'charlie', eastMeters: -5200, northMeters: 2200, altitudeMeters: 9_800 },
  { id: 'delta', eastMeters: 6800, northMeters: -3600, altitudeMeters: 10_600 },
  { id: 'echo', eastMeters: -7200, northMeters: -2800, altitudeMeters: 11_200 },
  { id: 'foxtrot', eastMeters: 10_500, northMeters: 4200, altitudeMeters: 9_600 },
  { id: 'golf', eastMeters: -12_500, northMeters: 5200, altitudeMeters: 11_800 },
  { id: 'hotel', eastMeters: 1800, northMeters: -11_200, altitudeMeters: 9_000 },
];

const AIRCRAFT_ICON_SVG = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24"><path fill="white" d="M2 16l8-2V5.5c0-.8.7-1.5 1.5-1.5S13 4.7 13 5.5V14l9 2v2l-9-1v3l2 1v1l-3-1-3 1v-1l2-1v-3l-8 1z"/></svg>`;

const AIRCRAFT_ICON_URL = `data:image/svg+xml,${encodeURIComponent(AIRCRAFT_ICON_SVG)}`;

function buildAircraftDemoPositions(origin: { lat: number; lon: number }) {
  const latRad = (origin.lat * Math.PI) / 180;
  const cosLat = Math.cos(latRad);
  const lonScale = Math.abs(cosLat) < 1e-6 ? Number.POSITIVE_INFINITY : METERS_PER_DEGREE_LAT * cosLat;

  return AIRCRAFT_POINTS.map((point) => {
    const lat = origin.lat + point.northMeters / METERS_PER_DEGREE_LAT;
    const lon = Number.isFinite(lonScale)
      ? origin.lon + point.eastMeters / lonScale
      : origin.lon;
    return {
      id: point.id,
      lat,
      lon,
      altitudeMeters: point.altitudeMeters,
    };
  });
}

export function AircraftDemoLayer({
  viewer,
  viewModeRoute,
  cameraPerspectiveId,
}: AircraftDemoLayerProps) {
  const enabled = useAircraftDemoStore((state) => state.enabled);
  const dataSourceRef = useRef<CustomDataSource | null>(null);
  const attachedViewerRef = useRef<Viewer | null>(null);
  const lastKeyRef = useRef<string | null>(null);

  useEffect(() => {
    const dataSource = dataSourceRef.current;
    const attachedViewer = attachedViewerRef.current;

    if (dataSource && attachedViewer && attachedViewer !== viewer) {
      attachedViewer.dataSources.remove(dataSource, false);
      attachedViewerRef.current = null;
      lastKeyRef.current = null;
    }

    if (!enabled || viewModeRoute.viewModeId !== 'local') {
      if (dataSource && attachedViewerRef.current === viewer) {
        viewer.dataSources.remove(dataSource, false);
        attachedViewerRef.current = null;
        lastKeyRef.current = null;
        viewer.scene.requestRender();
      }
      return;
    }

    const { lat, lon } = viewModeRoute;

    const source = dataSourceRef.current ?? new CustomDataSource('aircraft-demo');
    dataSourceRef.current = source;

    if (attachedViewerRef.current !== viewer) {
      void viewer.dataSources.add(source);
      attachedViewerRef.current = viewer;
    }

    const nextShow = cameraPerspectiveId === 'upward';
    if (source.show !== nextShow) source.show = nextShow;

    const nextKey = `${lat}:${lon}`;
    if (lastKeyRef.current !== nextKey) {
      lastKeyRef.current = nextKey;
      source.entities.removeAll();
      const positions = buildAircraftDemoPositions({ lat, lon });
      for (const position of positions) {
        source.entities.add(
          new Entity({
            id: `aircraft-demo:${position.id}`,
            position: Cartesian3.fromDegrees(position.lon, position.lat, position.altitudeMeters),
            billboard: {
              image: AIRCRAFT_ICON_URL,
              scale: 0.9,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
          }),
        );
      }
    }

    viewer.scene.requestRender();
  }, [cameraPerspectiveId, enabled, viewModeRoute, viewer]);

  useEffect(() => {
    return () => {
      const dataSource = dataSourceRef.current;
      const attachedViewer = attachedViewerRef.current;
      if (!dataSource || !attachedViewer) return;
      attachedViewer.dataSources.remove(dataSource, false);
      attachedViewerRef.current = null;
      lastKeyRef.current = null;
    };
  }, []);

  return null;
}
