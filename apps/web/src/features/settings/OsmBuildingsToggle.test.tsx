import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';

import { usePerformanceModeStore } from '../../state/performanceMode';
import { useOsmBuildingsStore } from '../../state/osmBuildings';
import OsmBuildingsToggle from './OsmBuildingsToggle';

beforeEach(() => {
  localStorage.removeItem('digital-earth.performanceMode');
  localStorage.removeItem('digital-earth.osmBuildings');
  usePerformanceModeStore.setState({ mode: 'high' });
  useOsmBuildingsStore.setState({ enabled: true });
});

test('toggles OSM buildings and persists', () => {
  render(<OsmBuildingsToggle />);

  const checkbox = screen.getByRole('checkbox', { name: '开启' });
  expect(checkbox).toBeChecked();

  fireEvent.click(checkbox);
  expect(useOsmBuildingsStore.getState().enabled).toBe(false);

  const stored = localStorage.getItem('digital-earth.osmBuildings');
  expect(stored).toMatch(/"enabled":false/);
});

test('disables OSM buildings toggle in low performance mode', () => {
  usePerformanceModeStore.setState({ mode: 'low' });
  useOsmBuildingsStore.setState({ enabled: true });

  render(<OsmBuildingsToggle />);

  const checkbox = screen.getByRole('checkbox', { name: 'Low 模式已关闭' });
  expect(checkbox).toBeDisabled();
  expect(checkbox).not.toBeChecked();
});

