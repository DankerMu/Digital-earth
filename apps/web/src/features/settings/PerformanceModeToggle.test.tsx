import { fireEvent, render, screen } from '@testing-library/react';

import PerformanceModeToggle from './PerformanceModeToggle';
import { usePerformanceModeStore } from '../../state/performanceMode';

beforeEach(() => {
  localStorage.removeItem('digital-earth.performanceMode');
  usePerformanceModeStore.setState({ enabled: false });
});

test('toggles performance mode and persists', () => {
  render(<PerformanceModeToggle />);

  const checkbox = screen.getByRole('checkbox', { name: '性能模式' });
  expect(checkbox).not.toBeChecked();

  fireEvent.click(checkbox);
  expect(checkbox).toBeChecked();

  const stored = localStorage.getItem('digital-earth.performanceMode');
  expect(stored).toMatch(/enabled":true/);
});
