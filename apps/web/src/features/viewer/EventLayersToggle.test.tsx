import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';

import { DEFAULT_EVENT_LAYER_MODE, useEventLayersStore } from '../../state/eventLayers';
import { EventLayersToggle } from './EventLayersToggle';

beforeEach(() => {
  localStorage.removeItem('digital-earth.eventLayers');
  useEventLayersStore.setState({ enabled: false, mode: DEFAULT_EVENT_LAYER_MODE });
});

test('toggles event layers UI and persists selection', async () => {
  const user = userEvent.setup();
  render(<EventLayersToggle />);

  expect(screen.getByText('默认隐藏，避免信息过载。')).toBeInTheDocument();

  const switchInput = screen.getByRole('checkbox', { name: '显示事件图层' });
  expect(switchInput).not.toBeChecked();

  await user.click(switchInput);
  expect(switchInput).toBeChecked();

  const diffButton = screen.getByRole('button', { name: '差值' });
  await user.click(diffButton);
  expect(diffButton).toHaveAttribute('aria-pressed', 'true');

  const stored = localStorage.getItem('digital-earth.eventLayers');
  expect(stored).toMatch(/"enabled":true/);
  expect(stored).toMatch(/"mode":"difference"/);
});

