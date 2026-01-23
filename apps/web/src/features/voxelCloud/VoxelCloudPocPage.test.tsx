import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

type MockVoxelCloudSnapshot = {
  ready: boolean;
  enabled: boolean;
  settings: {
    enabled: boolean;
    stepVoxels: number;
    maxSteps: number;
    densityMultiplier: number;
    extinction: number;
  };
  volume: unknown;
  recommended: { stepVoxels: number; stepMeters: number | null; maxSteps: number } | null;
  metrics: {
    url: string;
    bytes: number;
    fetchMs: number;
    decodeMs: number;
    atlasMs: number;
    canvasMs: number;
    totalMs: number;
    approxAtlasBytes: number;
  } | null;
  lastError: string | null;
};

const viewerMocks = vi.hoisted(() => {
  type PostRenderEvent = {
    addEventListener: (cb: () => void) => void;
    removeEventListener: (cb: () => void) => void;
    __mocks: { trigger: () => void };
  };

  return {
    instances: [] as Array<{
      scene: { postRender: PostRenderEvent; requestRenderMode: boolean; maximumRenderTimeChange: number };
      camera: { setView: ReturnType<typeof vi.fn> };
      destroy: ReturnType<typeof vi.fn>;
    }>,
  };
});

vi.mock('cesium', () => {
  const makeEvent = () => {
    const handlers = new Set<() => void>();
    return {
      addEventListener: (cb: () => void) => handlers.add(cb),
      removeEventListener: (cb: () => void) => handlers.delete(cb),
      __mocks: { trigger: () => handlers.forEach((cb) => cb()) },
    };
  };

  class Cartesian3 {
    static fromDegrees = vi.fn(() => ({ kind: 'cartesian3' }));
  }

  class EllipsoidTerrainProvider {}
  class WebMercatorTilingScheme {}
  class UrlTemplateImageryProvider {
    constructor(public readonly options: unknown) {}
  }
  class ImageryLayer {
    constructor(public readonly provider: unknown) {}
  }

  class Viewer {
    scene = {
      postRender: makeEvent(),
      requestRenderMode: false,
      maximumRenderTimeChange: 0,
    };
    camera = { setView: vi.fn() };
    destroy = vi.fn();
    constructor(public readonly container: Element, public readonly options: unknown) {
      void container;
      void options;
      viewerMocks.instances.push(this as never);
    }
  }

  return {
    Cartesian3,
    EllipsoidTerrainProvider,
    ImageryLayer,
    UrlTemplateImageryProvider,
    Viewer,
    WebMercatorTilingScheme,
  };
});

const rendererMocks = vi.hoisted(() => {
  return {
    instances: [] as Array<{
      getSnapshot: () => MockVoxelCloudSnapshot;
      setEnabled: ReturnType<typeof vi.fn>;
      updateSettings: ReturnType<typeof vi.fn>;
      loadFromUrl: ReturnType<typeof vi.fn>;
      destroy: ReturnType<typeof vi.fn>;
    }>,
    failLoad: false,
  };
});

vi.mock('./VoxelCloudRenderer', () => {
  const makeSnapshot = (): MockVoxelCloudSnapshot => ({
    ready: false,
    enabled: true,
    settings: {
      enabled: true,
      stepVoxels: 1,
      maxSteps: 128,
      densityMultiplier: 1.0,
      extinction: 1.2,
    },
    volume: null,
    recommended: null,
    metrics: null,
    lastError: null,
  });

  return {
    VoxelCloudRenderer: vi.fn(function (this: Record<string, unknown>) {
      let snapshot = makeSnapshot();

      const api = {
        getSnapshot: () => snapshot,
        setEnabled: vi.fn((enabled: boolean) => {
          snapshot = { ...snapshot, enabled, settings: { ...snapshot.settings, enabled } };
        }),
        updateSettings: vi.fn((partial: Record<string, unknown>) => {
          snapshot = { ...snapshot, settings: { ...snapshot.settings, ...partial } };
        }),
        loadFromUrl: vi.fn(async (url: string) => {
          if (rendererMocks.failLoad) {
            snapshot = { ...snapshot, lastError: 'load failed' };
            throw new Error('load failed');
          }
          snapshot = {
            ...snapshot,
            ready: true,
            metrics: {
              url,
              bytes: 123,
              fetchMs: 1,
              decodeMs: 2,
              atlasMs: 3,
              canvasMs: 4,
              totalMs: 10,
              approxAtlasBytes: 456,
            },
            recommended: { stepVoxels: 1, stepMeters: 12.5, maxSteps: 128 },
          };
        }),
        destroy: vi.fn(),
      };

      rendererMocks.instances.push(api as never);
      Object.assign(this, api);
    }),
  };
});

import { VoxelCloudPocPage } from './VoxelCloudPocPage';

describe('VoxelCloudPocPage', () => {
  beforeEach(() => {
    rendererMocks.instances.length = 0;
    viewerMocks.instances.length = 0;
    rendererMocks.failLoad = false;
    vi.clearAllMocks();
  });

  it('loads demo volume, updates settings, and toggles enabled', async () => {
    const nowSpy = vi.spyOn(performance, 'now');
    nowSpy.mockImplementationOnce(() => 0);
    nowSpy.mockImplementationOnce(() => 1000);

    render(<VoxelCloudPocPage />);

    expect(await screen.findByText('[ST-0109] Voxel Cloud PoC')).toBeInTheDocument();

    await waitFor(() => {
      expect(rendererMocks.instances.length).toBe(1);
      expect(viewerMocks.instances.length).toBe(1);
    });

    fireEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(await screen.findByText('Load metrics')).toBeInTheDocument();
    expect(screen.getByText('Recommended')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Step (voxels)'), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Max steps'), { target: { value: '200' } });
    fireEvent.change(screen.getByLabelText('Density ×'), { target: { value: '1.5' } });
    fireEvent.change(screen.getByLabelText('Extinction'), { target: { value: '0.9' } });

    const instance = rendererMocks.instances[0]!;
    expect(instance.updateSettings).toHaveBeenCalled();

    // Trigger post-render twice so fps monitor emits a sample.
    act(() => {
      viewerMocks.instances[0]!.scene.postRender.__mocks.trigger();
      viewerMocks.instances[0]!.scene.postRender.__mocks.trigger();
    });

    fireEvent.click(screen.getByRole('button', { name: /disable/i }));
    expect(instance.setEnabled).toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Reset' }));
    expect(instance.destroy).toHaveBeenCalled();
    expect(rendererMocks.instances.length).toBeGreaterThanOrEqual(2);
  });

  it('shows an error when loading fails', async () => {
    rendererMocks.failLoad = true;

    render(<VoxelCloudPocPage />);

    expect(await screen.findByText('[ST-0109] Voxel Cloud PoC')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(await screen.findByText(/load failed/i)).toBeInTheDocument();
  });
});
