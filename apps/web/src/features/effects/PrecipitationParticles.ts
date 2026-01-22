import {
  Cartesian2,
  Cartesian3,
  ConeEmitter,
  Matrix3,
  Matrix4,
  Math as CesiumMath,
  ParticleSystem,
  Transforms,
  type Viewer,
} from 'cesium';

import type { PrecipitationKind } from './weatherSampler';

export type PrecipitationParticleType = Exclude<PrecipitationKind, 'none'>;

export type PrecipitationParticlesOptions = {
  maxParticles?: number;
  maxParticlesPerformance?: number;
  maxCameraHeightMeters?: number;
  emitterHeightMeters?: number;
  emitterAngleDegrees?: number;
};

export type PrecipitationParticlesUpdate = {
  enabled: boolean;
  intensity: number;
  kind: PrecipitationKind;
  performanceModeEnabled: boolean;
};

const DEFAULT_MAX_PARTICLES = 2500;
const DEFAULT_MAX_CAMERA_HEIGHT_METERS = 20_000;
const DEFAULT_EMITTER_HEIGHT_METERS = 20;
const DEFAULT_EMITTER_ANGLE_DEGREES = 25;

type CanvasImage = HTMLCanvasElement;

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

function clamp01(value: number): number {
  return clamp(value, 0, 1);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function normalizeParticleType(kind: PrecipitationKind): PrecipitationParticleType {
  return kind === 'snow' ? 'snow' : 'rain';
}

function createRainImage(): CanvasImage {
  const canvas = document.createElement('canvas');
  canvas.width = 16;
  canvas.height = 16;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(9, 2);
  ctx.quadraticCurveTo(7, 9, 5, 14);
  ctx.stroke();
  ctx.restore();
  return canvas;
}

function createSnowImage(): CanvasImage {
  const canvas = document.createElement('canvas');
  canvas.width = 16;
  canvas.height = 16;
  const ctx = canvas.getContext('2d');
  if (!ctx) return canvas;
  ctx.save();
  ctx.beginPath();
  ctx.arc(8, 8, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
  return canvas;
}

function getCameraHeightMeters(viewer: Viewer): number | null {
  const camera = viewer.camera as unknown as { positionCartographic?: { height?: number } };
  const height = camera.positionCartographic?.height;
  if (!isFiniteNumber(height)) return null;
  return height;
}

function createEmitterModelMatrix(options: { emitterHeightMeters: number }): Matrix4 {
  const rotation = Matrix3.fromRotationX(CesiumMath.PI);
  const translation = new Cartesian3(0, 0, options.emitterHeightMeters);
  return Matrix4.fromRotationTranslation(rotation, translation);
}

function createParticleImageSize(kind: PrecipitationParticleType): {
  min: Cartesian2;
  max: Cartesian2;
} {
  if (kind === 'snow') {
    return {
      min: new Cartesian2(6, 6),
      max: new Cartesian2(12, 12),
    };
  }

  return {
    min: new Cartesian2(2, 10),
    max: new Cartesian2(4, 18),
  };
}

function avgParticleLifeSeconds(kind: PrecipitationParticleType): number {
  return kind === 'snow' ? 4.5 : 1.2;
}

function speedRangeMetersPerSecond(kind: PrecipitationParticleType): { min: number; max: number } {
  return kind === 'snow' ? { min: 1.0, max: 4.0 } : { min: 12.0, max: 22.0 };
}

function particleLifeRangeSeconds(kind: PrecipitationParticleType): { min: number; max: number } {
  return kind === 'snow' ? { min: 3.0, max: 6.0 } : { min: 0.8, max: 1.6 };
}

function emissionRateFor(options: {
  intensity: number;
  maxParticles: number;
  kind: PrecipitationParticleType;
}): number {
  const intensity = clamp01(options.intensity);
  if (intensity <= 0) return 0;
  const avgLife = avgParticleLifeSeconds(options.kind);
  const maxEmissionRate = avgLife > 0 ? options.maxParticles / avgLife : 0;
  const shaped = intensity ** 1.35;
  return Math.max(0, shaped * maxEmissionRate);
}

export class PrecipitationParticles {
  private readonly viewer: Viewer;
  private readonly baseRequestRenderMode: boolean;
  private readonly rainImage: CanvasImage;
  private readonly snowImage: CanvasImage;
  private readonly options: Required<PrecipitationParticlesOptions>;
  private particleSystem: ParticleSystem | null = null;
  private preUpdateHandler: (() => void) | null = null;
  private active = false;
  private activeType: PrecipitationParticleType = 'rain';

  constructor(viewer: Viewer, options: PrecipitationParticlesOptions = {}) {
    this.viewer = viewer;
    this.baseRequestRenderMode = viewer.scene.requestRenderMode;
    const maxParticles = options.maxParticles ?? DEFAULT_MAX_PARTICLES;
    this.options = {
      maxParticles,
      maxParticlesPerformance:
        options.maxParticlesPerformance ?? Math.floor(maxParticles * 0.5),
      maxCameraHeightMeters: options.maxCameraHeightMeters ?? DEFAULT_MAX_CAMERA_HEIGHT_METERS,
      emitterHeightMeters: options.emitterHeightMeters ?? DEFAULT_EMITTER_HEIGHT_METERS,
      emitterAngleDegrees: options.emitterAngleDegrees ?? DEFAULT_EMITTER_ANGLE_DEGREES,
    };
    this.rainImage = createRainImage();
    this.snowImage = createSnowImage();
  }

  update(update: PrecipitationParticlesUpdate): void {
    const intensity = clamp01(update.intensity);
    const requestedType = normalizeParticleType(update.kind);

    const maxParticles = update.performanceModeEnabled
      ? this.options.maxParticlesPerformance
      : this.options.maxParticles;

    const cameraHeight = getCameraHeightMeters(this.viewer);
    const underMaxHeight =
      cameraHeight == null || cameraHeight <= this.options.maxCameraHeightMeters;

    const shouldActivate =
      update.enabled &&
      update.kind !== 'none' &&
      intensity > 0 &&
      maxParticles > 0 &&
      underMaxHeight;

    if (!shouldActivate) {
      this.deactivate();
      return;
    }

    this.activateIfNeeded();

    this.activeType = requestedType;
    if (this.particleSystem) {
      this.particleSystem.show = true;
      this.applyType(this.particleSystem, requestedType);
      this.particleSystem.emissionRate = emissionRateFor({
        intensity,
        maxParticles,
        kind: requestedType,
      });
      this.viewer.scene.requestRender();
    }
  }

  destroy(): void {
    this.deactivate();
  }

  private activateIfNeeded(): void {
    if (this.active) return;
    this.active = true;
    this.viewer.scene.requestRenderMode = false;
    this.ensureParticleSystem();
    this.attachPreUpdate();
    this.viewer.scene.requestRender();
  }

  private deactivate(): void {
    if (!this.active && !this.particleSystem) return;
    this.active = false;
    this.detachPreUpdate();
    this.viewer.scene.requestRenderMode = this.baseRequestRenderMode;

    if (this.particleSystem) {
      const primitives = this.viewer.scene.primitives as unknown as {
        remove: (primitive: unknown) => boolean;
      };
      primitives.remove(this.particleSystem);
      this.particleSystem.destroy();
      this.particleSystem = null;
    }

    this.viewer.scene.requestRender();
  }

  private ensureParticleSystem(): void {
    if (this.particleSystem) return;

    const emitter = new ConeEmitter(
      CesiumMath.toRadians(this.options.emitterAngleDegrees),
    );

    const particleSystem = new ParticleSystem({
      show: true,
      emitter,
      modelMatrix: Matrix4.IDENTITY,
      emitterModelMatrix: createEmitterModelMatrix({
        emitterHeightMeters: this.options.emitterHeightMeters,
      }),
      emissionRate: 0,
      loop: true,
      lifetime: Number.MAX_VALUE,
      sizeInMeters: true,
    });

    this.applyType(particleSystem, this.activeType);

    const primitives = this.viewer.scene.primitives as unknown as {
      add: (primitive: unknown) => unknown;
    };
    primitives.add(particleSystem);
    this.particleSystem = particleSystem;
  }

  private attachPreUpdate(): void {
    if (this.preUpdateHandler) return;
    const scene = this.viewer.scene as unknown as {
      preUpdate?: { addEventListener?: (handler: () => void) => void };
    };
    const preUpdate = scene.preUpdate;
    if (!preUpdate?.addEventListener) return;

    const handler = () => {
      if (!this.particleSystem || !this.active) return;
      const camera = this.viewer.camera as unknown as {
        positionWC?: Cartesian3;
        position?: Cartesian3;
      };
      const position = camera.positionWC ?? camera.position;
      if (!position) return;
      this.particleSystem.modelMatrix = Transforms.eastNorthUpToFixedFrame(position);
    };

    preUpdate.addEventListener(handler);
    this.preUpdateHandler = handler;
  }

  private detachPreUpdate(): void {
    if (!this.preUpdateHandler) return;
    const scene = this.viewer.scene as unknown as {
      preUpdate?: { removeEventListener?: (handler: () => void) => void };
    };
    scene.preUpdate?.removeEventListener?.(this.preUpdateHandler);
    this.preUpdateHandler = null;
  }

  private applyType(particleSystem: ParticleSystem, kind: PrecipitationParticleType): void {
    const imageSize = createParticleImageSize(kind);
    const life = particleLifeRangeSeconds(kind);
    const speed = speedRangeMetersPerSecond(kind);

    particleSystem.image = kind === 'snow' ? this.snowImage : this.rainImage;
    particleSystem.minimumImageSize = imageSize.min;
    particleSystem.maximumImageSize = imageSize.max;
    particleSystem.minimumParticleLife = life.min;
    particleSystem.maximumParticleLife = life.max;
    particleSystem.minimumSpeed = speed.min;
    particleSystem.maximumSpeed = speed.max;
  }
}
