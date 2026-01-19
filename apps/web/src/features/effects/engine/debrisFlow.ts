import type { EffectPresetItem } from '../types';

import { parseRgba, rgbaString, withAlpha } from './color';

export type DebrisParticle = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
  age: number;
  ttl: number;
};

export type DebrisFlowEngineOptions = {
  preset: EffectPresetItem;
  width: number;
  height: number;
  random?: () => number;
};

export class DebrisFlowEngine {
  private preset: EffectPresetItem;
  private width: number;
  private height: number;
  private random: () => number;
  private particles: DebrisParticle[] = [];
  private spawnCarry = 0;
  private elapsed = 0;
  private baseColor;

  constructor(options: DebrisFlowEngineOptions) {
    this.preset = options.preset;
    this.width = Math.max(1, options.width);
    this.height = Math.max(1, options.height);
    this.random = options.random ?? Math.random;
    this.baseColor = parseRgba(this.preset.color_hint);
  }

  setPreset(preset: EffectPresetItem): void {
    this.preset = preset;
    this.baseColor = parseRgba(this.preset.color_hint);
    this.reset();
  }

  resize(width: number, height: number): void {
    this.width = Math.max(1, width);
    this.height = Math.max(1, height);
  }

  reset(): void {
    this.particles = [];
    this.spawnCarry = 0;
    this.elapsed = 0;
  }

  getParticleCount(): number {
    return this.particles.length;
  }

  isExpired(): boolean {
    return this.preset.duration > 0 && this.elapsed >= this.preset.duration;
  }

  tick(dtSeconds: number): void {
    const dt = Math.max(0, Math.min(dtSeconds, 0.05));
    this.elapsed += dt;

    const intensityScale = 0.7 + this.preset.intensity * 0.25;
    const spawnRate = this.preset.spawn_rate * intensityScale;
    const maxParticles = Math.min(700, 200 + this.preset.intensity * 150);

    this.spawnCarry += spawnRate * dt;
    const toSpawn = Math.min(
      Math.floor(this.spawnCarry),
      Math.max(0, maxParticles - this.particles.length),
    );
    this.spawnCarry -= toSpawn;
    for (let i = 0; i < toSpawn; i += 1) {
      this.particles.push(this.spawnParticle());
    }

    const baseSpeed = 60 + this.preset.intensity * 45;
    const wind = this.preset.wind_influence;
    for (const particle of this.particles) {
      const noise = (this.random() - 0.5) * wind * 60;
      particle.vx += noise * dt;
      particle.vx *= 1 - 0.05 * dt;

      particle.x += particle.vx * dt;
      particle.y += (particle.vy + baseSpeed) * dt;

      particle.age += dt;
    }

    this.particles = this.particles.filter((p) => {
      if (p.age >= p.ttl) return false;
      if (p.y - p.radius > this.height + 20) return false;
      return true;
    });
  }

  render(ctx: CanvasRenderingContext2D): void {
    ctx.clearRect(0, 0, this.width, this.height);
    this.renderDecal(ctx);
    this.renderParticles(ctx);
  }

  private renderDecal(ctx: CanvasRenderingContext2D): void {
    const decalAlpha = Math.max(0.08, Math.min(0.3, this.baseColor.a * 0.35));
    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.strokeStyle = rgbaString(withAlpha(this.baseColor, decalAlpha));

    const w = this.width;
    const h = this.height;
    const widthScale = 0.18 + this.preset.intensity * 0.03;
    ctx.lineWidth = Math.max(16, w * widthScale);

    ctx.beginPath();
    ctx.moveTo(w * 0.25, h * 0.05);
    ctx.quadraticCurveTo(w * 0.55, h * 0.25, w * 0.42, h * 0.55);
    ctx.quadraticCurveTo(w * 0.32, h * 0.78, w * 0.55, h * 1.05);
    ctx.stroke();
    ctx.restore();
  }

  private renderParticles(ctx: CanvasRenderingContext2D): void {
    const base = this.baseColor;
    for (const particle of this.particles) {
      const life = 1 - particle.age / particle.ttl;
      const alpha = Math.max(0, Math.min(1, base.a * life));
      ctx.fillStyle = rgbaString(withAlpha(base, alpha));

      ctx.beginPath();
      ctx.arc(particle.x, particle.y, particle.radius, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  private spawnParticle(): DebrisParticle {
    const w = this.width;
    const h = this.height;

    const startX = w * 0.25;
    const endX = w * 0.55;
    const t = this.random();
    const channelX = startX + (endX - startX) * t + (this.random() - 0.5) * w * 0.08;

    const sizeRange = this.preset.particle_size;
    const radius =
      sizeRange.min + (sizeRange.max - sizeRange.min) * this.random();

    const vy = 40 + this.random() * 60 + this.preset.intensity * 20;
    const vx = (this.random() - 0.5) * (25 + this.preset.wind_influence * 80);

    const ttl = Math.max(
      0.6,
      Math.min(3.5, h / Math.max(120, vy + 60) + 0.6 + this.random() * 0.6),
    );

    return { x: channelX, y: -radius, vx, vy, radius, age: 0, ttl };
  }
}
