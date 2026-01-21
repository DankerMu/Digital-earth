import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('cesium', () => {
  const Matrix4 = {
    IDENTITY: { kind: 'identity' },
    fromRotationTranslation: vi.fn(() => ({ kind: 'rotation-translation' })),
  };

  const Matrix3 = {
    fromRotationX: vi.fn(() => ({ kind: 'rot-x' })),
  };

  const Cartesian3 = vi.fn(function (x: number, y: number, z: number) {
    return { x, y, z };
  });

  const Cartesian2 = vi.fn(function (x: number, y: number) {
    return { x, y };
  });

  const ConeEmitter = vi.fn(function (angle: number) {
    return { kind: 'cone-emitter', angle };
  });

  const ParticleSystem = vi.fn(function (options: unknown) {
    return {
      ...(options as Record<string, unknown>),
      destroy: vi.fn(),
    };
  });

  const Transforms = {
    eastNorthUpToFixedFrame: vi.fn(() => ({ kind: 'enu' })),
  };

  const CesiumMath = {
    PI: Math.PI,
    toRadians: vi.fn((degrees: number) => (degrees * Math.PI) / 180),
  };

  return {
    Cartesian2,
    Cartesian3,
    ConeEmitter,
    Matrix3,
    Matrix4,
    Math: CesiumMath,
    ParticleSystem,
    Transforms,
  };
});

import { Matrix4, ParticleSystem } from 'cesium';
import { PrecipitationParticles } from './PrecipitationParticles';

function makeViewer() {
  const preUpdateHandlers = new Set<() => void>();

  return {
    camera: {
      position: { x: 1, y: 2, z: 3 },
      positionCartographic: { height: 100 },
    },
    scene: {
      requestRenderMode: true,
      requestRender: vi.fn(),
      primitives: {
        add: vi.fn((primitive: unknown) => primitive),
        remove: vi.fn(() => true),
      },
      preUpdate: {
        addEventListener: vi.fn((handler: () => void) => {
          preUpdateHandlers.add(handler);
        }),
        removeEventListener: vi.fn((handler: () => void) => {
          preUpdateHandlers.delete(handler);
        }),
      },
      __mocks: {
        triggerPreUpdate: () => {
          for (const handler of preUpdateHandlers) handler();
        },
      },
    },
  };
}

describe('PrecipitationParticles', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('creates and updates a Cesium ParticleSystem for rain', () => {
    const viewer = makeViewer();
    const particles = new PrecipitationParticles(viewer as never, {
      maxParticles: 1200,
      maxParticlesPerformance: 0,
    });

    particles.update({
      enabled: true,
      intensity: 1,
      kind: 'rain',
      performanceModeEnabled: false,
    });

    expect(vi.mocked(ParticleSystem)).toHaveBeenCalledTimes(1);

    const instance = vi.mocked(ParticleSystem).mock.results[0]?.value as {
      show?: boolean;
      emissionRate?: number;
      modelMatrix?: unknown;
    };

    expect(instance.show).toBe(true);
    expect(instance.emissionRate).toBeGreaterThan(0);
    expect(viewer.scene.primitives.add).toHaveBeenCalledWith(instance);
    expect(viewer.scene.requestRenderMode).toBe(false);

    (viewer.scene as unknown as { __mocks: { triggerPreUpdate: () => void } }).__mocks.triggerPreUpdate();
    expect(instance.modelMatrix).toEqual(expect.objectContaining({ kind: 'enu' }));
  });

  it('switches particle type and disables itself in performance mode (default)', () => {
    const viewer = makeViewer();
    const particles = new PrecipitationParticles(viewer as never, {
      maxParticles: 2000,
      maxParticlesPerformance: 0,
    });

    particles.update({
      enabled: true,
      intensity: 0.8,
      kind: 'snow',
      performanceModeEnabled: false,
    });

    const instance = vi.mocked(ParticleSystem).mock.results[0]?.value as {
      image?: unknown;
    };
    expect(instance.image).toBeInstanceOf(HTMLCanvasElement);

    viewer.scene.primitives.remove.mockClear();

    particles.update({
      enabled: true,
      intensity: 0.8,
      kind: 'snow',
      performanceModeEnabled: true,
    });

    expect(viewer.scene.primitives.remove).toHaveBeenCalledWith(instance);
    expect(viewer.scene.requestRenderMode).toBe(true);
  });

  it('deactivates when camera is above the configured height', () => {
    const viewer = makeViewer();
    viewer.camera.positionCartographic.height = 50_000;

    const particles = new PrecipitationParticles(viewer as never, {
      maxCameraHeightMeters: 10_000,
      maxParticles: 2000,
    });

    particles.update({
      enabled: true,
      intensity: 1,
      kind: 'rain',
      performanceModeEnabled: false,
    });

    expect(vi.mocked(ParticleSystem)).not.toHaveBeenCalled();
    expect(viewer.scene.primitives.add).not.toHaveBeenCalled();
  });

  it('cleans up primitives on destroy', () => {
    const viewer = makeViewer();
    const particles = new PrecipitationParticles(viewer as never, {
      maxParticles: 2000,
      maxParticlesPerformance: 0,
    });

    particles.update({
      enabled: true,
      intensity: 1,
      kind: 'rain',
      performanceModeEnabled: false,
    });

    const instance = vi.mocked(ParticleSystem).mock.results[0]?.value as {
      destroy: () => void;
    };

    particles.destroy();

    expect(viewer.scene.primitives.remove).toHaveBeenCalledWith(instance);
    expect(vi.mocked(Matrix4.fromRotationTranslation)).toHaveBeenCalled();
    expect(instance.destroy).toHaveBeenCalledTimes(1);
  });
});

