import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test } from 'vitest';

import PerformanceModeToggle from './PerformanceModeToggle';
import { usePerformanceModeStore } from '../../state/performanceMode';

beforeEach(() => {
  localStorage.removeItem('digital-earth.performanceMode');
  usePerformanceModeStore.setState({ mode: 'high' });
});

test('switches performance mode and persists', () => {
  render(<PerformanceModeToggle />);

  const highRadio = screen.getByRole('radio', { name: 'High' });
  const lowRadio = screen.getByRole('radio', { name: 'Low' });
  expect(highRadio).toBeChecked();
  expect(lowRadio).not.toBeChecked();

  fireEvent.click(lowRadio);
  expect(lowRadio).toBeChecked();

  const stored = localStorage.getItem('digital-earth.performanceMode');
  expect(stored).toMatch(/"mode":"low"/);
});
