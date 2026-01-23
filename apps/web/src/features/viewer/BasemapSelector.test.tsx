import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';

import { DEFAULT_BASEMAP_ID } from '../../config/basemaps';
import { useBasemapStore } from '../../state/basemap';
import { BasemapSelector } from './BasemapSelector';

beforeEach(() => {
  localStorage.removeItem('digital-earth.basemap');
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
});

function readPersistedBasemapId(): string | null {
  const raw = localStorage.getItem('digital-earth.basemap');
  if (!raw) return null;
  const parsed = JSON.parse(raw) as unknown;
  if (!parsed || typeof parsed !== 'object') return null;
  const record = parsed as Record<string, unknown>;
  const basemapId = record.basemapId;
  return typeof basemapId === 'string' ? basemapId : null;
}

test('selects basemap and persists to localStorage', async () => {
  const user = userEvent.setup();
  render(<BasemapSelector ionEnabled />);

  const select = screen.getByRole('combobox', { name: '底图' });
  expect(select).toHaveValue(DEFAULT_BASEMAP_ID);

  expect(screen.getByRole('option', { name: 'Bing Maps (Cesium ion)' })).toBeInTheDocument();

  await user.selectOptions(select, 'nasa-gibs-blue-marble');
  expect(select).toHaveValue('nasa-gibs-blue-marble');

  expect(readPersistedBasemapId()).toBe('nasa-gibs-blue-marble');
  expect(select).toHaveAccessibleDescription(/Blue Marble Next Generation/);

  await user.selectOptions(select, 'ion-world-imagery');
  expect(select).toHaveValue('ion-world-imagery');
  expect(readPersistedBasemapId()).toBe('ion-world-imagery');
  expect(select).toHaveAccessibleDescription(/Cesium Ion/);
});

test('disables Cesium ion basemaps when ionEnabled is false', () => {
  render(<BasemapSelector ionEnabled={false} />);

  const option = screen.getByRole('option', { name: 'Bing Maps (Cesium ion)' });
  expect(option).toBeDisabled();
});
