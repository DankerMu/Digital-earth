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

  const monitoringButton = screen.getByRole('button', { name: '监测' });
  expect(monitoringButton).toHaveAttribute('aria-pressed', 'true');

  const diffButton = screen.getByRole('button', { name: '差值' });
  await user.click(diffButton);
  expect(diffButton).toHaveAttribute('aria-pressed', 'true');

  await user.click(switchInput);
  expect(switchInput).not.toBeChecked();
  expect(screen.getByText('关闭后隐藏，避免信息过载。')).toBeInTheDocument();

  const stored = localStorage.getItem('digital-earth.eventLayers');
  expect(stored).toMatch(/"enabled":false/);
  expect(stored).toMatch(/"mode":"difference"/);
});
