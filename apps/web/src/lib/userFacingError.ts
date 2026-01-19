import { isHttpError } from './http';

export type UserFacingError = {
  title: string;
  message: string;
  status?: number;
};

export function toUserFacingError(error: unknown): UserFacingError {
  if (isHttpError(error)) {
    if (error.status === 404) {
      return {
        title: '资源不存在',
        message: '请求的资源不存在（404）。请检查地址或稍后重试。',
        status: 404,
      };
    }
    if (error.status === 429) {
      return {
        title: '请求过于频繁',
        message: '请求过于频繁（429），请稍后重试。',
        status: 429,
      };
    }
    if (error.status >= 500) {
      return {
        title: '服务繁忙',
        message: `服务端暂时不可用（${error.status}），请稍后重试。`,
        status: error.status,
      };
    }

    return {
      title: '请求失败',
      message: `请求失败（${error.status}）。请稍后重试。`,
      status: error.status,
    };
  }

  if (error instanceof Error) {
    if (error.message === 'Network Error') {
      return {
        title: '网络异常',
        message: '网络连接异常，请检查网络后重试。',
      };
    }

    const message = error.message.trim();
    return {
      title: '发生错误',
      message: message.length > 0 ? message : '发生未知错误，请稍后重试。',
    };
  }

  return {
    title: '发生错误',
    message: '发生未知错误，请稍后重试。',
  };
}
