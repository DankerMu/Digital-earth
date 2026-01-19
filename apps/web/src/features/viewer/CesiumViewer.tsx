import {
  Cartesian3,
  ImageryLayer,
  Viewer,
  type Viewer as CesiumViewerInstance
} from 'cesium';
import { useEffect, useRef, useState } from 'react';
import { getBasemapById, type BasemapId } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { BasemapSelector } from './BasemapSelector';
import { CompassControl } from './CompassControl';
import { createImageryProviderForBasemap, setViewerBasemap } from './cesiumBasemap';
import 'cesium/Build/Cesium/Widgets/widgets.css';

const DEFAULT_CAMERA = {
  longitude: 116.391,
  latitude: 39.9075,
  heightMeters: 20_000_000
} as const;

const MIN_ZOOM_DISTANCE_METERS = 100;
const MAX_ZOOM_DISTANCE_METERS = 40_000_000;

export function CesiumViewer() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [viewer, setViewer] = useState<CesiumViewerInstance | null>(null);
  const basemapId = useBasemapStore((state) => state.basemapId);
  const appliedBasemapIdRef = useRef<BasemapId | null>(null);

  useEffect(() => {
    const defaultDestination = Cartesian3.fromDegrees(
      DEFAULT_CAMERA.longitude,
      DEFAULT_CAMERA.latitude,
      DEFAULT_CAMERA.heightMeters
    );

    const initialBasemapId = useBasemapStore.getState().basemapId;
    const initialBasemap = getBasemapById(initialBasemapId);
    if (!initialBasemap) {
      throw new Error(`Unknown basemap id: ${initialBasemapId}`);
    }
    appliedBasemapIdRef.current = initialBasemapId;

    const newViewer = new Viewer(containerRef.current!, {
      baseLayer: new ImageryLayer(
        // Avoid Cesium ion default imagery (Bing) by always passing an explicit base layer.
        createImageryProviderForBasemap(initialBasemap),
      ),
      baseLayerPicker: false,
      geocoder: false,
      animation: false,
      timeline: false,
      fullscreenButton: false,
      sceneModePicker: false,
      navigationHelpButton: false,
      infoBox: false,
      selectionIndicator: false,
      homeButton: true
    });

    newViewer.scene.requestRenderMode = true;
    newViewer.scene.maximumRenderTimeChange = Infinity;

    newViewer.camera.setView({ destination: defaultDestination });

    const controller = newViewer.scene.screenSpaceCameraController;
    controller.minimumZoomDistance = MIN_ZOOM_DISTANCE_METERS;
    controller.maximumZoomDistance = MAX_ZOOM_DISTANCE_METERS;

    newViewer.homeButton.viewModel.command.beforeExecute.addEventListener((e) => {
      e.cancel = true;
      newViewer.camera.flyTo({ destination: defaultDestination, duration: 0.8 });
    });

    setViewer(newViewer);

    return () => {
      newViewer.destroy();
    };
  }, []);

  useEffect(() => {
    if (!viewer) return;
    if (appliedBasemapIdRef.current === basemapId) return;
    const basemap = getBasemapById(basemapId);
    if (!basemap) return;

    setViewerBasemap(viewer, basemap);
    appliedBasemapIdRef.current = basemapId;
  }, [basemapId, viewer]);

  return (
    <div className="viewerRoot">
      <div ref={containerRef} className="viewerCanvas" data-testid="cesium-container" />
      <div className="viewerOverlay">
        {viewer ? <CompassControl viewer={viewer} /> : null}
        <BasemapSelector />
      </div>
    </div>
  );
}
