export class HttpError extends Error {
  public readonly status: number;
  public readonly url: string;
  public readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    options: { status: number; url: string; retryAfterSeconds?: number; cause?: unknown }
  ) {
    super(message);
    this.name = 'HttpError';
    this.status = options.status;
    this.url = options.url;
    this.retryAfterSeconds = options.retryAfterSeconds;

    if (options.cause) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (this as any).cause = options.cause;
    }
  }
}

function parseRetryAfterSeconds(retryAfterHeader: string | null): number | undefined {
  if (!retryAfterHeader) return undefined;

  const seconds = Number(retryAfterHeader);
  if (!Number.isNaN(seconds) && seconds >= 0) return seconds;

  const date = new Date(retryAfterHeader);
  const ms = date.getTime();
  if (!Number.isNaN(ms)) {
    const deltaSeconds = Math.ceil((ms - Date.now()) / 1000);
    return deltaSeconds > 0 ? deltaSeconds : 0;
  }

  return undefined;
}

export function isHttpError(error: unknown): error is HttpError {
  return error instanceof HttpError;
}

export async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    throw new Error('Network Error', { cause: error });
  }

  if (!response.ok) {
    const retryAfterSeconds = parseRetryAfterSeconds(
      response.headers.get('retry-after')
    );
    throw new HttpError(`Request failed: ${response.status}`, {
      status: response.status,
      url,
      retryAfterSeconds,
    });
  }

  return (await response.json()) as T;
}

