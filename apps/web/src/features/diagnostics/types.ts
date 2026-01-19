export type DiagnosticsMemory = {
  usedBytes: number;
  totalBytes?: number;
  limitBytes?: number;
};

export type DiagnosticsRequests = {
  total: number;
  tileTotal: number;
  failed: number;
  tileFailed: number;
  cacheHits: number;
  tileCacheHits: number;
};

export type DiagnosticsRequestLogEntry = {
  at: number;
  url: string;
  method: string;
  ok: boolean;
  status?: number;
  durationMs: number;
  isTile: boolean;
};

export type DiagnosticsErrorLogEntry = {
  at: number;
  message: string;
  stack?: string;
};

export type DiagnosticsSnapshot = {
  enabled: boolean;
  fps?: number;
  memory?: DiagnosticsMemory;
  requests: DiagnosticsRequests;
  errorsTotal: number;
  requestLogs: DiagnosticsRequestLogEntry[];
  errorLogs: DiagnosticsErrorLogEntry[];
};

