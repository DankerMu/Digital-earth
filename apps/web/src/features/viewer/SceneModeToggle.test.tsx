import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test } from 'vitest';

import { DEFAULT_SCENE_MODE_ID, useSceneModeStore } from '../../state/sceneMode';
import { SceneModeToggle } from './SceneModeToggle';

beforeEach(() => {
  localStorage.removeItem('digital-earth.sceneMode');
  useSceneModeStore.setState({ sceneModeId: DEFAULT_SCENE_MODE_ID });
});

test('switches scene mode and persists to localStorage', async () => {
  const user = userEvent.setup();
  render(<SceneModeToggle />);

  const button3d = screen.getByRole('button', { name: '3D' });
  const button2d = screen.getByRole('button', { name: '2D' });

  expect(button3d).toHaveAttribute('aria-pressed', 'true');
  expect(button2d).toHaveAttribute('aria-pressed', 'false');

  await user.click(button2d);

  expect(button3d).toHaveAttribute('aria-pressed', 'false');
  expect(button2d).toHaveAttribute('aria-pressed', 'true');
  expect(localStorage.getItem('digital-earth.sceneMode')).toMatch(/"sceneModeId":"2d"/);
});
