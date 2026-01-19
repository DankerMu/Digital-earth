import { describe, expect, it } from 'vitest';

import type { EffectPresetItem } from '../types';

import { DebrisFlowEngine } from './debrisFlow';

function makePreset(overrides: Partial<EffectPresetItem> = {}): EffectPresetItem {
  return {
    id: 'demo',
    effect_type: 'debris_flow',
    intensity: 3,
    duration: 1,
    color_hint: 'rgba(90, 60, 40, 0.95)',
    spawn_rate: 120,
    particle_size: { min: 1, max: 2 },
    wind_influence: 0.2,
    risk_level: 'high',
    ...overrides,
  };
}

describe('DebrisFlowEngine', () => {
  it('spawns particles as time advances', () => {
    const engine = new DebrisFlowEngine({
      preset: makePreset({ intensity: 2, duration: 10 }),
      width: 300,
      height: 200,
      random: () => 0.5,
    });

    engine.tick(0.5);
    expect(engine.getParticleCount()).toBeGreaterThan(0);
  });

  it('respects duration expiry', () => {
    const engine = new DebrisFlowEngine({
      preset: makePreset({ duration: 0.1 }),
      width: 300,
      height: 200,
      random: () => 0.5,
    });
    engine.tick(0.05);
    engine.tick(0.05);
    engine.tick(0.05);
    expect(engine.isExpired()).toBe(true);
  });

  it('reset clears particles and time', () => {
    const engine = new DebrisFlowEngine({
      preset: makePreset({ duration: 10 }),
      width: 300,
      height: 200,
      random: () => 0.5,
    });

    engine.tick(0.5);
    expect(engine.getParticleCount()).toBeGreaterThan(0);

    engine.reset();
    expect(engine.getParticleCount()).toBe(0);
    expect(engine.isExpired()).toBe(false);
  });
});
