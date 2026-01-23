import { act, render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAircraftDemoStore } from '../../state/aircraftDemo';
import { AircraftDemoLayer } from './AircraftDemoLayer';

const cesiumMocks = vi.hoisted(() => {
  return {
    customDataSources: [] as Array<{
      name: string;
      show: boolean;
      entities: { add: ReturnType<typeof vi.fn>; removeAll: ReturnType<typeof vi.fn> };
    }>,
    fromDegrees: vi.fn((lon: number, lat: number, height: number) => ({ lon, lat, height })),
  };
});

vi.mock('cesium', () => {
  return {
    Cartesian3: {
      fromDegrees: cesiumMocks.fromDegrees,
    },
    CustomDataSource: vi.fn(function (name: string) {
      const instance = {
        name,
        show: true,
        entities: {
          add: vi.fn((entity: unknown) => entity),
          removeAll: vi.fn(),
        },
      };
      cesiumMocks.customDataSources.push(instance);
      return instance;
    }),
    Entity: vi.fn(function (options: unknown) {
      return { ...(options as Record<string, unknown>) };
    }),
  };
});

function createViewerStub() {
  return {
    dataSources: {
      add: vi.fn(async (dataSource: unknown) => dataSource),
      remove: vi.fn(() => true),
    },
    scene: {
      requestRender: vi.fn(),
    },
  };
}

beforeEach(() => {
  localStorage.removeItem('digital-earth.aircraftDemo');
  useAircraftDemoStore.setState({ enabled: false });
  cesiumMocks.customDataSources.length = 0;
  cesiumMocks.fromDegrees.mockClear();
});

describe('AircraftDemoLayer', () => {
  it('is lazy when disabled', async () => {
    const viewer = createViewerStub();

    render(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).not.toHaveBeenCalled();
    });
    expect(cesiumMocks.customDataSources).toHaveLength(0);
  });

  it('adds an aircraft data source in local mode when enabled', async () => {
    const viewer = createViewerStub();

    useAircraftDemoStore.getState().setEnabled(true);

    render(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).toHaveBeenCalledTimes(1);
    });

    expect(cesiumMocks.customDataSources).toHaveLength(1);
    const dataSource = cesiumMocks.customDataSources[0];
    expect(dataSource.name).toBe('aircraft-demo');
    expect(dataSource.show).toBe(true);
    expect(dataSource.entities.removeAll).toHaveBeenCalledTimes(1);
    expect(dataSource.entities.add).toHaveBeenCalled();

    const heights = cesiumMocks.fromDegrees.mock.calls.map((call) => call[2]);
    expect(heights.length).toBeGreaterThan(0);
    for (const height of heights) {
      expect(height).toBeGreaterThanOrEqual(9000);
      expect(height).toBeLessThanOrEqual(12000);
    }
  });

  it('hides aircraft when not in upward perspective', async () => {
    const viewer = createViewerStub();
    useAircraftDemoStore.getState().setEnabled(true);

    render(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="forward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).toHaveBeenCalledTimes(1);
    });

    expect(cesiumMocks.customDataSources[0]?.show).toBe(false);
  });

  it('removes the data source when leaving local mode or disabling', async () => {
    const viewer = createViewerStub();
    useAircraftDemoStore.getState().setEnabled(true);

    const { rerender } = render(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).toHaveBeenCalledTimes(1);
    });

    rerender(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'global' }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.remove).toHaveBeenCalledTimes(1);
    });

    rerender(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).toHaveBeenCalledTimes(2);
    });

    act(() => {
      useAircraftDemoStore.getState().setEnabled(false);
    });

    await waitFor(() => {
      expect(viewer.dataSources.remove).toHaveBeenCalledTimes(2);
    });
  });

  it('rebuilds aircraft positions when local origin changes', async () => {
    const viewer = createViewerStub();
    useAircraftDemoStore.getState().setEnabled(true);

    const { rerender } = render(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 30, lon: 120 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(viewer.dataSources.add).toHaveBeenCalledTimes(1);
    });

    const dataSource = cesiumMocks.customDataSources[0];
    expect(dataSource.entities.removeAll).toHaveBeenCalledTimes(1);

    rerender(
      <AircraftDemoLayer
        viewer={viewer as never}
        viewModeRoute={{ viewModeId: 'local', lat: 31, lon: 121 }}
        cameraPerspectiveId="upward"
      />,
    );

    await waitFor(() => {
      expect(dataSource.entities.removeAll).toHaveBeenCalledTimes(2);
    });
  });
});
