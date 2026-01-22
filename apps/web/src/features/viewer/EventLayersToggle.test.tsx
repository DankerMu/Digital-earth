import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';

import { DEFAULT_EVENT_LAYER_MODE, useEventLayersStore } from '../../state/eventLayers';
import { EventLayersToggle } from './EventLayersToggle';

beforeEach(() => {
  localStorage.removeItem('digital-earth.eventLayers');
  useEventLayersStore.setState({ enabled: true, mode: DEFAULT_EVENT_LAYER_MODE });
});

test('toggles event layers UI and persists selection', async () => {
  const user = userEvent.setup();
  render(<EventLayersToggle />);

  const switchInput = screen.getByRole('checkbox', { name: '显示事件图层' });
  expect(switchInput).toBeChecked();

  expect(screen.getByRole('radiogroup', { name: '事件图层切换' })).toBeInTheDocument();

  const monitoringButton = screen.getByRole('radio', { name: '监测' });
  expect(monitoringButton).toHaveAttribute('aria-checked', 'true');

  const diffButton = screen.getByRole('radio', { name: '差值' });
  await user.click(diffButton);
  expect(diffButton).toHaveAttribute('aria-checked', 'true');

  await user.click(switchInput);
  expect(switchInput).not.toBeChecked();
  expect(screen.getByText('关闭后隐藏，避免信息过载。')).toBeInTheDocument();

  const stored = localStorage.getItem('digital-earth.eventLayers');
  expect(stored).toMatch(/"enabled":false/);
  expect(stored).toMatch(/"mode":"difference"/);
});

test('shows loading and unavailable indicators', () => {
  render(<EventLayersToggle historyStatus="loading" differenceStatus="error" />);

  expect(screen.getByRole('radio', { name: /历史.*加载中/ })).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: /差值.*不可用/ })).toBeInTheDocument();
});
