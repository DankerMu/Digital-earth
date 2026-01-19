import { HttpError } from './http';
import { toUserFacingError } from './userFacingError';

test('maps 5xx to service busy message', () => {
  const error = new HttpError('Request failed: 503', { status: 503, url: '/x' });
  expect(toUserFacingError(error)).toEqual({
    title: '服务繁忙',
    message: '服务端暂时不可用（503），请稍后重试。',
    status: 503,
  });
});

test('maps non-404/429 http errors to generic request failed', () => {
  const error = new HttpError('Request failed: 400', { status: 400, url: '/x' });
  expect(toUserFacingError(error)).toEqual({
    title: '请求失败',
    message: '请求失败（400）。请稍后重试。',
    status: 400,
  });
});

test('maps network error to chinese message', () => {
  const error = new Error('Network Error');
  expect(toUserFacingError(error)).toEqual({
    title: '网络异常',
    message: '网络连接异常，请检查网络后重试。',
  });
});

test('handles unknown values', () => {
  expect(toUserFacingError(123)).toEqual({
    title: '发生错误',
    message: '发生未知错误，请稍后重试。',
  });
});

