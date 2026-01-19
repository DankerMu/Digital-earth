import { render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import ErrorBoundary from './ErrorBoundary';

function Bomb(): never {
  throw new Error('boom');
}

test('supports fallbackRender', () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  render(
    <ErrorBoundary
      fallbackRender={({ error }) => (
        <div>
          自定义兜底：{error instanceof Error ? error.message : 'unknown'}
        </div>
      )}
    >
      <Bomb />
    </ErrorBoundary>
  );

  expect(screen.getByText('自定义兜底：boom')).toBeInTheDocument();

  consoleError.mockRestore();
});
