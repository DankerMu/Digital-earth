import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import React from 'react';
import { describe, expect, it, vi } from 'vitest';

import type { EffectPresetItem } from './types';

import { DisasterDemo } from './DisasterDemo';

function makePreset(overrides: Partial<EffectPresetItem> = {}): EffectPresetItem {
  return {
    id: 'debris_flow_low',
    effect_type: 'debris_flow',
    intensity: 2,
    duration: 1,
    color_hint: 'rgba(120, 85, 60, 0.85)',
    spawn_rate: 120,
    particle_size: { min: 1, max: 3 },
    wind_influence: 0.15,
    risk_level: 'low',
    ...overrides,
  };
}

describe('DisasterDemo', () => {
  it('loads presets and allows play/stop', async () => {
    document.body.innerHTML = '<div id="effect-stage"></div>';
    const presets = [
      makePreset({ id: 'debris_flow_low', intensity: 2 }),
      makePreset({ id: 'debris_flow_extreme', intensity: 5, spawn_rate: 350 }),
    ];

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        return {
          ok: true,
          json: async () => presets,
        } as unknown as Response;
      }),
    );

    const raf = vi.fn(() => 1);
    const caf = vi.fn();
    vi.stubGlobal('requestAnimationFrame', raf);
    vi.stubGlobal('cancelAnimationFrame', caf);

    render(<DisasterDemo apiBaseUrl="http://localhost:8000" />);

    expect(await screen.findByLabelText('预设')).toBeInTheDocument();

    const play = screen.getByRole('button', { name: '播放' });
    const stop = screen.getByRole('button', { name: '停止' });
    expect(play).toBeEnabled();
    expect(stop).toBeDisabled();

    await userEvent.click(play);
    expect(stop).toBeEnabled();
    expect(raf).toHaveBeenCalled();

    await userEvent.click(stop);
    expect(caf).toHaveBeenCalled();
  });

  it('switching preset stops playback', async () => {
    document.body.innerHTML = '<div id="effect-stage"></div>';
    const presets = [
      makePreset({ id: 'debris_flow_low', intensity: 2 }),
      makePreset({ id: 'debris_flow_medium', intensity: 3 }),
    ];

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        return {
          ok: true,
          json: async () => presets,
        } as unknown as Response;
      }),
    );

    vi.stubGlobal('requestAnimationFrame', vi.fn(() => 1));
    vi.stubGlobal('cancelAnimationFrame', vi.fn());

    render(<DisasterDemo apiBaseUrl="http://localhost:8000" />);
    const select = await screen.findByLabelText('预设');
    const play = screen.getByRole('button', { name: '播放' });
    const stop = screen.getByRole('button', { name: '停止' });

    await userEvent.click(play);
    expect(stop).toBeEnabled();

    await userEvent.selectOptions(select, 'debris_flow_medium');
    expect(stop).toBeDisabled();
  });
});
