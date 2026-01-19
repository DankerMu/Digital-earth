import http from "k6/http";
import { check, sleep } from "k6";
import { SharedArray } from "k6/data";
import { Counter } from "k6/metrics";

function _requiredEnv(name) {
  const value = __ENV[name];
  if (value === undefined || value === null || String(value).trim() === "") {
    throw new Error(`Missing required env var: ${name}`);
  }
  return String(value);
}

function _envInt(name, fallback) {
  const raw = __ENV[name];
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return fallback;
  }
  const value = parseInt(String(raw), 10);
  if (Number.isNaN(value)) {
    throw new Error(`Invalid int for ${name}: ${raw}`);
  }
  return value;
}

function _envFloat(name, fallback) {
  const raw = __ENV[name];
  if (raw === undefined || raw === null || String(raw).trim() === "") {
    return fallback;
  }
  const value = parseFloat(String(raw));
  if (Number.isNaN(value)) {
    throw new Error(`Invalid float for ${name}: ${raw}`);
  }
  return value;
}

function _loadConfig() {
  const configPath = __ENV.CONFIG || "./config/staging.json";
  let raw;
  try {
    raw = open(configPath);
  } catch (err) {
    throw new Error(`Failed to read config at ${configPath}: ${String(err)}`);
  }

  let cfg;
  try {
    cfg = JSON.parse(raw);
  } catch (err) {
    throw new Error(`Invalid JSON config at ${configPath}: ${String(err)}`);
  }

  return cfg;
}

function _pick(array) {
  return array[Math.floor(Math.random() * array.length)];
}

function _formatTemplate(template, values) {
  return template.replace(/\{([a-zA-Z0-9_]+)\}/g, (_, key) => {
    if (values[key] === undefined || values[key] === null) {
      return `{${key}}`;
    }
    return String(values[key]);
  });
}

function _toQueryString(params) {
  const entries = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null);
  if (entries.length === 0) {
    return "";
  }
  return (
    "?" +
    entries
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
      .join("&")
  );
}

function _getHeader(headers, name) {
  if (!headers) {
    return undefined;
  }
  const target = String(name).toLowerCase();
  for (const [k, v] of Object.entries(headers)) {
    if (String(k).toLowerCase() === target) {
      return Array.isArray(v) ? v.join(",") : String(v);
    }
  }
  return undefined;
}

function _classifyCdnCache(res, config) {
  const explicitHeader = config?.cdn?.hit_header_name;
  if (explicitHeader) {
    const value = _getHeader(res.headers, explicitHeader);
    if (value !== undefined) {
      const lowered = value.toLowerCase();
      const hitValues = (config?.cdn?.hit_header_values || []).map((s) => String(s).toLowerCase());
      const missValues = (config?.cdn?.miss_header_values || []).map((s) => String(s).toLowerCase());
      if (hitValues.some((x) => lowered.includes(x))) {
        return { category: "hit", signal: `${explicitHeader}: ${value}` };
      }
      if (missValues.some((x) => lowered.includes(x))) {
        return { category: "miss", signal: `${explicitHeader}: ${value}` };
      }
    }
  }

  const cf = _getHeader(res.headers, "cf-cache-status");
  if (cf !== undefined) {
    const v = cf.toUpperCase();
    if (v === "HIT" || v === "REVALIDATED") {
      return { category: "hit", signal: `cf-cache-status: ${cf}` };
    }
    if (
      v === "MISS" ||
      v === "BYPASS" ||
      v === "DYNAMIC" ||
      v === "EXPIRED" ||
      v === "UPDATING" ||
      v === "STALE"
    ) {
      return { category: "miss", signal: `cf-cache-status: ${cf}` };
    }
  }

  const xCache = _getHeader(res.headers, "x-cache");
  if (xCache !== undefined) {
    const v = xCache.toLowerCase();
    if (v.includes("miss") || v.includes("bypass") || v.includes("expired")) {
      return { category: "miss", signal: `x-cache: ${xCache}` };
    }
    if (v.includes("hit")) {
      return { category: "hit", signal: `x-cache: ${xCache}` };
    }
  }

  const xCacheHits = _getHeader(res.headers, "x-cache-hits");
  if (xCacheHits !== undefined) {
    const hits = parseInt(String(xCacheHits), 10);
    if (!Number.isNaN(hits)) {
      return {
        category: hits > 0 ? "hit" : "miss",
        signal: `x-cache-hits: ${xCacheHits}`,
      };
    }
  }

  const age = _getHeader(res.headers, "age");
  if (age !== undefined) {
    const seconds = parseInt(String(age), 10);
    if (!Number.isNaN(seconds) && seconds > 0) {
      return { category: "hit", signal: `age: ${age}` };
    }
  }

  return { category: "unknown", signal: "no-cache-headers" };
}

function _responseSizeBytes(res) {
  const contentLength = _getHeader(res.headers, "content-length");
  if (contentLength !== undefined) {
    const v = parseInt(String(contentLength), 10);
    if (!Number.isNaN(v) && v >= 0) {
      return v;
    }
  }

  if (res.body && typeof res.body === "object" && "byteLength" in res.body) {
    return res.body.byteLength;
  }

  if (typeof res.body === "string") {
    return res.body.length;
  }

  return 0;
}

const config = _loadConfig();
const scenario = __ENV.SCENARIO || config.default_scenario || "ramp";

const tilePaths = config.tile?.paths_file
  ? new SharedArray("tilePaths", () =>
      open(String(config.tile.paths_file))
        .split(/\r?\n/)
        .map((l) => l.trim())
        .filter((l) => l.length > 0 && !l.startsWith("#"))
    )
  : null;

const cdnHits = new Counter("cdn_hits");
const cdnMisses = new Counter("cdn_misses");
const cdnUnknown = new Counter("cdn_unknown");
const bytesTotal = new Counter("bytes_total");
const bytesHit = new Counter("bytes_hit");
const bytesMiss = new Counter("bytes_miss");
const bytesUnknown = new Counter("bytes_unknown");

function _scenarioConfig(name) {
  const fromConfig = config.scenarios?.[name];
  if (fromConfig) {
    return fromConfig;
  }

  if (name === "sustained") {
    return {
      executor: "constant-vus",
      vus: _envInt("VUS", 20),
      duration: __ENV.DURATION || "10m",
      gracefulStop: "30s",
    };
  }

  if (name === "spike") {
    const baseline = _envInt("BASELINE_VUS", 5);
    const spike = _envInt("SPIKE_VUS", 50);
    return {
      executor: "ramping-vus",
      stages: [
        { duration: "1m", target: baseline },
        { duration: "10s", target: spike },
        { duration: "1m", target: spike },
        { duration: "10s", target: baseline },
        { duration: "1m", target: baseline },
        { duration: "30s", target: 0 },
      ],
      gracefulRampDown: "30s",
      gracefulStop: "30s",
    };
  }

  const start = _envInt("RAMP_START_VUS", 1);
  const target = _envInt("RAMP_TARGET_VUS", 20);
  return {
    executor: "ramping-vus",
    stages: [
      { duration: "1m", target: start },
      { duration: "2m", target: target },
      { duration: "5m", target: target },
      { duration: "1m", target: 0 },
    ],
    gracefulRampDown: "30s",
    gracefulStop: "30s",
  };
}

export const options = {
  discardResponseBodies: Boolean(config.request?.discard_response_bodies ?? true),
  insecureSkipTLSVerify: Boolean(config.request?.insecure_skip_tls_verify),
  thresholds: Object.assign(
    {
      http_req_failed: ["rate<0.01"],
      http_req_duration: ["p(95)<1500"],
    },
    config.thresholds || {}
  ),
  tags: {
    env: String(config.name || "unknown"),
    scenario: String(scenario),
  },
  scenarios: {
    tiles: _scenarioConfig(String(scenario)),
  },
};

export default function () {
  const baseUrl = _requiredEnv("BASE_URL");
  const tileConfig = config.tile || {};
  const pathTemplate = String(tileConfig.path_template || "/tiles/{z}/{x}/{y}.png");

  let url;
  if (tilePaths && tilePaths.length > 0) {
    const chosen = String(_pick(tilePaths));
    url = chosen.startsWith("http://") || chosen.startsWith("https://") ? chosen : baseUrl + chosen;
  } else {
    const zooms = tileConfig.zooms || (tileConfig.zoom !== undefined ? [tileConfig.zoom] : [6]);
    const z = parseInt(String(_pick(zooms)), 10);
    const rangeMax = Math.pow(2, z) - 1;
    const [xmin, xmax] = tileConfig.x_range || [0, rangeMax];
    const [ymin, ymax] = tileConfig.y_range || [0, rangeMax];
    const x = xmin + Math.floor(Math.random() * (xmax - xmin + 1));
    const y = ymin + Math.floor(Math.random() * (ymax - ymin + 1));

    const placeholders = Object.assign({}, tileConfig.placeholders || {}, { z, x, y });
    url = baseUrl + _formatTemplate(pathTemplate, placeholders);
  }

  const cacheBust = Boolean(tileConfig.cache_bust);
  const queryParams = Object.assign({}, tileConfig.query_params || {});
  if (cacheBust) {
    queryParams.cb = `${__VU}-${__ITER}-${Date.now()}`;
  }
  url += _toQueryString(queryParams);

  const headers = Object.assign({}, config.headers || {}, {
    Accept: "*/*",
  });

  const timeoutMs = _envInt("TIMEOUT_MS", config.request?.timeout_ms ?? 30000);
  const res = http.get(url, {
    headers,
    timeout: `${timeoutMs}ms`,
    responseType: "binary",
    redirects: 0,
    tags: { endpoint: "tile" },
  });

  const expectedStatuses = config.request?.expected_statuses || [200];
  check(res, {
    "status expected": (r) => expectedStatuses.includes(r.status),
  });

  const sizeBytes = _responseSizeBytes(res);
  bytesTotal.add(sizeBytes);

  const cache = _classifyCdnCache(res, config);
  if (cache.category === "hit") {
    cdnHits.add(1);
    bytesHit.add(sizeBytes);
  } else if (cache.category === "miss") {
    cdnMisses.add(1);
    bytesMiss.add(sizeBytes);
  } else {
    cdnUnknown.add(1);
    bytesUnknown.add(sizeBytes);
  }

  const pauseSeconds = _envFloat("SLEEP_SECONDS", config.request?.sleep_seconds ?? 0);
  if (pauseSeconds > 0) {
    sleep(pauseSeconds);
  }
}
