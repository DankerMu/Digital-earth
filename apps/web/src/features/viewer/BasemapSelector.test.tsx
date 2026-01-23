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

test('selects basemap and persists to localStorage', async () => {
  const user = userEvent.setup();
  render(<BasemapSelector />);

  const select = screen.getByRole('combobox', { name: '底图' });
  expect(select).toHaveValue(DEFAULT_BASEMAP_ID);

  expect(screen.getByRole('option', { name: 'Bing Maps (Cesium ion)' })).toBeInTheDocument();

  await user.selectOptions(select, 'nasa-gibs-blue-marble');
  expect(select).toHaveValue('nasa-gibs-blue-marble');

  expect(localStorage.getItem('digital-earth.basemap')).toMatch(/nasa-gibs-blue-marble/);
  expect(screen.getByLabelText('Basemap description')).toHaveTextContent('Blue Marble');

  await user.selectOptions(select, 'ion-world-imagery');
  expect(select).toHaveValue('ion-world-imagery');
  expect(localStorage.getItem('digital-earth.basemap')).toMatch(/ion-world-imagery/);
  expect(screen.getByLabelText('Basemap description')).toHaveTextContent('Cesium Ion');
});
