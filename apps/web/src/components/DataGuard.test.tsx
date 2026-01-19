import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import DataGuard from './DataGuard';

test('shows overlay when data is unavailable', () => {
  const { container } = render(
    <DataGuard isAvailable={false} message="缺数据">
      <div>内容</div>
    </DataGuard>
  );

  expect(container.querySelector('[data-unavailable="true"]')).toBeTruthy();
  expect(screen.getByText('内容')).toBeInTheDocument();
  expect(screen.getByText('缺数据')).toBeInTheDocument();
});

test('renders children directly when data is available', () => {
  const { container } = render(
    <DataGuard isAvailable message="缺数据">
      <div>内容</div>
    </DataGuard>
  );

  expect(container.querySelector('[data-unavailable="true"]')).toBeFalsy();
  expect(screen.getByText('内容')).toBeInTheDocument();
  expect(screen.queryByText('缺数据')).toBeNull();
});

test('uses default message when message is missing', () => {
  render(
    <DataGuard isAvailable={false}>
      <div>内容</div>
    </DataGuard>
  );

  expect(screen.getByText('数据缺失，已降级展示。')).toBeInTheDocument();
});
