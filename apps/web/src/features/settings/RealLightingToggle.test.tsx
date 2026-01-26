import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';

import { usePerformanceModeStore } from '../../state/performanceMode';
import { useRealLightingStore } from '../../state/realLighting';
import RealLightingToggle from './RealLightingToggle';

beforeEach(() => {
  localStorage.removeItem('digital-earth.performanceMode');
  localStorage.removeItem('digital-earth.realLighting');
  usePerformanceModeStore.setState({ mode: 'high' });
  useRealLightingStore.setState({ enabled: true });
});

test('toggles real lighting and persists', () => {
  render(<RealLightingToggle />);

  const checkbox = screen.getByRole('checkbox', { name: '真实光照（性能开销）' });
  expect(checkbox).toBeChecked();

  const statusId = checkbox.getAttribute('aria-describedby');
  expect(statusId).toBeTruthy();
  expect(document.getElementById(statusId!)).toHaveTextContent('开启');

  fireEvent.click(checkbox);
  expect(useRealLightingStore.getState().enabled).toBe(false);

  const stored = localStorage.getItem('digital-earth.realLighting');
  expect(stored).toMatch(/"enabled":false/);
});

test('disables real lighting toggle in low performance mode', () => {
  usePerformanceModeStore.setState({ mode: 'low' });
  useRealLightingStore.setState({ enabled: true });

  render(<RealLightingToggle />);

  const checkbox = screen.getByRole('checkbox', { name: '真实光照（性能开销）' });
  expect(checkbox).toBeDisabled();
  expect(checkbox).not.toBeChecked();

  const statusId = checkbox.getAttribute('aria-describedby');
  expect(statusId).toBeTruthy();
  expect(document.getElementById(statusId!)).toHaveTextContent('Low 模式下禁用');
});
