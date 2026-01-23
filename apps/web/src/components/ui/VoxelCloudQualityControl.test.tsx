import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const STORAGE_KEY = 'digital-earth.performanceMode';

async function importFresh() {
  vi.resetModules();
  const mod = await import('./VoxelCloudQualityControl');
  const store = await import('../../state/performanceMode');
  return { ...mod, ...store };
}

describe('VoxelCloudQualityControl', () => {
  it('updates voxel cloud quality and auto-downgrade in the performance store', async () => {
    localStorage.removeItem(STORAGE_KEY);
    const { VoxelCloudQualityControl, usePerformanceModeStore } = await importFresh();
    const user = userEvent.setup();

    render(<VoxelCloudQualityControl />);

    const select = screen.getByLabelText('Voxel cloud quality') as HTMLSelectElement;
    expect(select.value).toBe('high');

    fireEvent.change(select, { target: { value: 'unknown' } });
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('high');

    await user.selectOptions(select, 'low');
    expect(usePerformanceModeStore.getState().voxelCloudQuality).toBe('low');

    const checkbox = screen.getByLabelText('Auto-downgrade (FPS)') as HTMLInputElement;
    expect(checkbox.checked).toBe(true);
    await user.click(checkbox);
    expect(usePerformanceModeStore.getState().autoDowngrade).toBe(false);

    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as Record<string, unknown> | null;
    expect(persisted).toMatchObject({ voxelCloudQuality: 'low', autoDowngrade: false });
  });
});

