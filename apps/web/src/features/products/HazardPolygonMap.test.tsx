import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

type ScreenSpaceEventTypeMap = Record<string, string>;
type Action = (movement: unknown) => void;

type ViewerTestInstance = {
  __options: unknown;
  canvas: {
    addEventListener: ReturnType<typeof vi.fn>;
    removeEventListener: ReturnType<typeof vi.fn>;
  };
  scene: {
    pickPositionSupported: boolean;
    pickPosition: ReturnType<typeof vi.fn>;
    pick: ReturnType<typeof vi.fn>;
    requestRender: ReturnType<typeof vi.fn>;
  };
  entities: { _entities: unknown[] };
  __getAction: (type: string) => Action;
  destroy: ReturnType<typeof vi.fn>;
};

type TestingApi = {
  getLastViewer: () => unknown;
  reset: () => void;
  setImageryThrows: (value: boolean) => void;
};

type CesiumTestModule = {
  ScreenSpaceEventType: ScreenSpaceEventTypeMap;
  __testing: TestingApi;
};

vi.mock('cesium', () => {
  const viewerInstances: unknown[] = [];
  let imageryThrows = false;

  class Cartesian2 {
    x: number;
    y: number;

    constructor(x: number, y: number) {
      this.x = x;
      this.y = y;
    }
  }

  class Color {
    private name: string;

    constructor(name: string) {
      this.name = name;
    }

    withAlpha(alpha: number) {
      void alpha;
      return new Color(this.name);
    }

    static CYAN = new Color('CYAN');
    static WHITE = new Color('WHITE');
    static BLACK = new Color('BLACK');
  }

  class EllipsoidTerrainProvider {}

  class PropertyBag {
    private readonly value: unknown;

    constructor(value?: unknown) {
      this.value = value ?? {};
    }

    getValue() {
      return this.value;
    }
  }

  class ConstantProperty {
    private value: unknown;

    constructor(value?: unknown) {
      this.value = value;
    }

    setValue(value: unknown) {
      this.value = value;
    }

    getValue() {
      return this.value;
    }
  }

  class ConstantPositionProperty extends ConstantProperty {}

  class ColorMaterialProperty {
    color: unknown;

    constructor(color?: unknown) {
      this.color = color;
    }
  }

  class Entity {
    id: string;

    constructor(options?: { id?: string }) {
      this.id = options?.id ?? '';
    }
  }

  class PolygonHierarchy {
    positions: unknown[];

    constructor(positions: unknown[]) {
      this.positions = positions;
    }
  }

  const ScreenSpaceEventType = {
    LEFT_DOWN: 'LEFT_DOWN',
    LEFT_UP: 'LEFT_UP',
    MOUSE_MOVE: 'MOUSE_MOVE',
    LEFT_CLICK: 'LEFT_CLICK',
    LEFT_DOUBLE_CLICK: 'LEFT_DOUBLE_CLICK',
    RIGHT_CLICK: 'RIGHT_CLICK',
  } as const;

  const CesiumMath = {
    toDegrees: (radians: number) => (radians * 180) / Math.PI,
  };

  const Cartesian3 = {
    fromDegrees: (lon: number, lat: number, height?: number) => ({ lon, lat, height }),
  };

  const Cartographic = {
    fromCartesian: (cartesian: { longitude?: number; latitude?: number }) => ({
      longitude: cartesian.longitude ?? 0,
      latitude: cartesian.latitude ?? 0,
    }),
  };

  class UrlTemplateImageryProvider {
    constructor(...args: unknown[]) {
      void args;
    }
  }

  class ImageryLayer {
    provider: unknown;

    constructor(provider: unknown) {
      if (imageryThrows) throw new Error('imagery blocked');
      this.provider = provider;
    }
  }

  class WebMercatorTilingScheme {
    constructor(...args: unknown[]) {
      void args;
    }
  }

  class Viewer {
    __options: unknown;
    canvas = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    };
    camera = {
      setView: vi.fn(),
      pickEllipsoid: vi.fn(() => null),
    };
    entities = {
      _entities: [] as unknown[],
      add: (entity: unknown) => {
        this.entities._entities.push(entity);
        return entity;
      },
      remove: vi.fn((entity: unknown) => {
        this.entities._entities = this.entities._entities.filter((entry) => entry !== entity);
      }),
    };
    scene = {
      pickPositionSupported: true,
      pickPosition: vi.fn(() => null),
      pick: vi.fn(() => null),
      requestRender: vi.fn(),
      globe: { ellipsoid: {} },
      screenSpaceCameraController: {
        enableRotate: true,
        enableTranslate: true,
      },
    };
    screenSpaceEventHandler = {
      setInputAction: (cb: Action, type: string) => {
        this.actions.set(type, cb);
      },
      removeInputAction: (type: string) => {
        this.actions.delete(type);
      },
    };

    private actions = new Map<string, Action>();
    resize = vi.fn();
    destroy = vi.fn();

    constructor(container: unknown, options?: unknown) {
      void container;
      this.__options = options ?? null;
      viewerInstances.push(this);
    }

    __getAction(type: string): Action {
      const action = this.actions.get(type);
      if (!action) throw new Error(`Missing action: ${type}`);
      return action;
    }
  }

  return {
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
    Math: CesiumMath,
    PolygonHierarchy,
    PropertyBag,
    ScreenSpaceEventType,
    UrlTemplateImageryProvider,
    Viewer,
    WebMercatorTilingScheme,
    __testing: {
      getLastViewer: () => viewerInstances.at(-1) ?? null,
      reset: () => {
        viewerInstances.length = 0;
        imageryThrows = false;
      },
      setImageryThrows: (value: boolean) => {
        imageryThrows = value;
      },
    },
  };
});

import * as Cesium from 'cesium';

import { HazardPolygonMap } from './HazardPolygonMap';

function degreesToRadians(value: number): number {
  return (value * Math.PI) / 180;
}

function getCesiumModule(): CesiumTestModule {
  return Cesium as unknown as CesiumTestModule;
}

async function getViewerInstance(): Promise<ViewerTestInstance> {
  const { __testing } = getCesiumModule();

  return await waitFor(() => {
    const instance = __testing.getLastViewer();
    expect(instance).toBeTruthy();
    return instance as ViewerTestInstance;
  });
}

function getEntityProperties(entity: unknown): unknown {
  const props = (entity as { properties?: { getValue?: () => unknown } }).properties;
  return props?.getValue?.() ?? null;
}

describe('HazardPolygonMap', () => {
  it('adds vertices on click while drawing', async () => {
    const { __testing, ScreenSpaceEventType } = getCesiumModule();
    __testing.reset();
    const onChangeVertices = vi.fn();

    render(
      <HazardPolygonMap
        hazards={[{ id: 'h1', vertices: [] }]}
        activeHazardId="h1"
        drawing
        onSetActiveHazardId={vi.fn()}
        onChangeVertices={onChangeVertices}
        onDeleteVertex={vi.fn()}
        onFinishDrawing={vi.fn()}
      />,
    );

    const viewer = await getViewerInstance();
    expect(viewer.__options).toMatchObject({
      requestRenderMode: true,
    });
    expect((viewer.__options as { baseLayer?: unknown }).baseLayer).not.toBe(false);
    expect(viewer.scene.requestRender).toHaveBeenCalled();
    expect(viewer.canvas.addEventListener).toHaveBeenCalledWith('contextmenu', expect.any(Function));

    viewer.scene.pickPosition.mockReturnValue({
      longitude: degreesToRadians(10),
      latitude: degreesToRadians(20),
    });

    viewer.__getAction(ScreenSpaceEventType.LEFT_CLICK)({ position: { x: 1, y: 2 } });

    expect(onChangeVertices).toHaveBeenCalledWith('h1', [{ lon: 10, lat: 20 }]);
  });

  it('selects a hazard polygon on click while idle', async () => {
    const { __testing, ScreenSpaceEventType } = getCesiumModule();
    __testing.reset();
    const onSetActiveHazardId = vi.fn();

    render(
      <HazardPolygonMap
        hazards={[
          {
            id: 'h1',
            vertices: [
              { lon: 0, lat: 0 },
              { lon: 1, lat: 0 },
              { lon: 1, lat: 1 },
            ],
          },
        ]}
        activeHazardId={null}
        drawing={false}
        onSetActiveHazardId={onSetActiveHazardId}
        onChangeVertices={vi.fn()}
        onDeleteVertex={vi.fn()}
        onFinishDrawing={vi.fn()}
      />,
    );

    const viewer = await getViewerInstance();
    expect(viewer.entities._entities.length).toBeGreaterThan(0);

    const polygonEntity = viewer.entities._entities.find((entity) => {
      const props = getEntityProperties(entity);
      return (
        Boolean(props) &&
        (props as { kind?: unknown }).kind === 'hazardPolygon' &&
        (props as { hazardId?: unknown }).hazardId === 'h1'
      );
    });
    expect(polygonEntity).toBeTruthy();

    viewer.scene.pick.mockReturnValue({ id: polygonEntity });
    viewer.__getAction(ScreenSpaceEventType.LEFT_CLICK)({ position: { x: 3, y: 4 } });

    expect(onSetActiveHazardId).toHaveBeenCalledWith('h1');
  });

  it('drags and deletes vertices', async () => {
    const { __testing, ScreenSpaceEventType } = getCesiumModule();
    __testing.reset();
    const onChangeVertices = vi.fn();
    const onDeleteVertex = vi.fn();

    render(
      <HazardPolygonMap
        hazards={[{ id: 'h1', vertices: [{ lon: 0, lat: 0 }] }]}
        activeHazardId="h1"
        drawing={false}
        onSetActiveHazardId={vi.fn()}
        onChangeVertices={onChangeVertices}
        onDeleteVertex={onDeleteVertex}
        onFinishDrawing={vi.fn()}
      />,
    );

    const viewer = await getViewerInstance();

    const vertexEntity = viewer.entities._entities.find((entity) => {
      const props = getEntityProperties(entity);
      return (
        Boolean(props) &&
        (props as { kind?: unknown }).kind === 'hazardVertex' &&
        (props as { hazardId?: unknown }).hazardId === 'h1'
      );
    });
    expect(vertexEntity).toBeTruthy();

    viewer.scene.pick.mockReturnValue({ id: vertexEntity });
    viewer.scene.pickPosition.mockReturnValue({
      longitude: degreesToRadians(2),
      latitude: degreesToRadians(3),
    });

    viewer.__getAction(ScreenSpaceEventType.LEFT_DOWN)({ position: { x: 10, y: 10 } });
    viewer.__getAction(ScreenSpaceEventType.MOUSE_MOVE)({ endPosition: { x: 11, y: 11 } });
    viewer.__getAction(ScreenSpaceEventType.LEFT_UP)({});

    expect(onChangeVertices).toHaveBeenCalledWith('h1', [{ lon: 2, lat: 3 }]);

    viewer.__getAction(ScreenSpaceEventType.RIGHT_CLICK)({ position: { x: 10, y: 10 } });
    expect(onDeleteVertex).toHaveBeenCalledWith('h1', 0);

    // The click immediately after dragging should be ignored.
    viewer.__getAction(ScreenSpaceEventType.LEFT_CLICK)({ position: { x: 10, y: 10 } });
    expect(onChangeVertices).toHaveBeenCalledTimes(1);
  });

  it('finishes drawing on double click', async () => {
    const { __testing, ScreenSpaceEventType } = getCesiumModule();
    __testing.reset();
    const onFinishDrawing = vi.fn();

    render(
      <HazardPolygonMap
        hazards={[{ id: 'h1', vertices: [] }]}
        activeHazardId="h1"
        drawing
        onSetActiveHazardId={vi.fn()}
        onChangeVertices={vi.fn()}
        onDeleteVertex={vi.fn()}
        onFinishDrawing={onFinishDrawing}
      />,
    );

    const viewer = await getViewerInstance();
    viewer.__getAction(ScreenSpaceEventType.LEFT_DOUBLE_CLICK)({});
    expect(onFinishDrawing).toHaveBeenCalledTimes(1);
  });

  it('ignores imagery failures and destroys the viewer on unmount', async () => {
    const { __testing } = getCesiumModule();
    __testing.reset();
    __testing.setImageryThrows(true);

    const { unmount } = render(
      <HazardPolygonMap
        hazards={[{ id: 'h1', vertices: [] }]}
        activeHazardId="h1"
        drawing={false}
        onSetActiveHazardId={vi.fn()}
        onChangeVertices={vi.fn()}
        onDeleteVertex={vi.fn()}
        onFinishDrawing={vi.fn()}
      />,
    );

    const viewer = await getViewerInstance();
    expect(viewer.__options).toMatchObject({ baseLayer: false });
    unmount();
    expect(viewer.destroy).toHaveBeenCalledTimes(1);
  });
});
