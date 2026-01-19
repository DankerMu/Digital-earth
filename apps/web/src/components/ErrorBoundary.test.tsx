import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { expect, test, vi } from 'vitest';

import ErrorBoundary from './ErrorBoundary';

function Bomb({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error('boom');
  }
  return <div>ok</div>;
}

function Harness() {
  const [shouldThrow, setShouldThrow] = useState(true);
  return (
    <ErrorBoundary onReset={() => setShouldThrow(false)}>
      <Bomb shouldThrow={shouldThrow} />
    </ErrorBoundary>
  );
}

test('renders fallback and can reset', () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
  render(<Harness />);

  expect(screen.getByText('发生错误')).toBeInTheDocument();
  expect(screen.getByText('boom')).toBeInTheDocument();

  fireEvent.click(screen.getByRole('button', { name: '重试' }));
  expect(screen.getByText('ok')).toBeInTheDocument();

  consoleError.mockRestore();
});
