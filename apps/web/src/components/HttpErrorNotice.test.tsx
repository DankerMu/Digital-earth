import { render, screen } from '@testing-library/react';

import { HttpError } from '../lib/http';
import HttpErrorNotice from './HttpErrorNotice';

test('renders 429 user message', () => {
  render(
    <HttpErrorNotice
      error={new HttpError('Request failed: 429', { status: 429, url: '/x' })}
    />
  );

  expect(screen.getByRole('alert', { name: 'error-429' })).toBeInTheDocument();
  expect(screen.getByText('请求过于频繁')).toBeInTheDocument();
  expect(screen.getByText(/稍后重试/)).toBeInTheDocument();
});

test('renders 404 user message', () => {
  render(
    <HttpErrorNotice
      error={new HttpError('Request failed: 404', { status: 404, url: '/x' })}
    />
  );

  expect(screen.getByRole('alert', { name: 'error-404' })).toBeInTheDocument();
  expect(screen.getByText('资源不存在')).toBeInTheDocument();
});

