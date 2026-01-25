import type { Page, Route } from '@playwright/test';

const ONE_BY_ONE_PNG_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOeLk1sAAAAASUVORK5CYII=';

export const E2E_PRODUCT_ID = 1;
export const E2E_RISK_POI_IDS = [1001, 1002] as const;

const E2E_TIME_VALID_FROM = '2025-01-01T00:00:00Z';
const E2E_TIME_VALID_TO = '2025-01-02T00:00:00Z';

const E2E_BBOX = {
  min_x: 0,
  min_y: 0,
  max_x: 1,
  max_y: 1,
};

const E2E_POLYGON = {
  type: 'Polygon',
  coordinates: [
    [
      [0, 0],
      [1, 0],
      [1, 1],
      [0, 1],
      [0, 0],
    ],
  ],
} as const;

const PRODUCTS_RESPONSE = {
  page: 1,
  page_size: 50,
  total: 1,
  items: [
    {
      id: E2E_PRODUCT_ID,
      title: 'E2E Mock Event',
      hazards: [
        {
          severity: 'high',
          geometry: E2E_POLYGON,
          bbox: E2E_BBOX,
        },
      ],
    },
  ],
};

const PRODUCT_DETAIL_RESPONSE = {
  id: E2E_PRODUCT_ID,
  title: 'E2E Mock Event',
  text: 'Used for Playwright E2E tests.',
  issued_at: E2E_TIME_VALID_FROM,
  valid_from: E2E_TIME_VALID_FROM,
  valid_to: E2E_TIME_VALID_TO,
  version: 1,
  status: 'published',
  hazards: [
    {
      id: 101,
      severity: 'high',
      geometry: {
        type: 'Feature',
        properties: {},
        geometry: E2E_POLYGON,
      },
      bbox: E2E_BBOX,
      valid_from: E2E_TIME_VALID_FROM,
      valid_to: E2E_TIME_VALID_TO,
    },
  ],
};

const RISK_POIS_RESPONSE = {
  page: 1,
  page_size: 100,
  total: 2,
  items: [
    {
      id: E2E_RISK_POI_IDS[0],
      name: '测试风险点A',
      type: 'landslide',
      lon: 0.5,
      lat: 0.5,
      alt: null,
      weight: 1,
      tags: ['e2e'],
      risk_level: 3,
    },
    {
      id: E2E_RISK_POI_IDS[1],
      name: '测试风险点B',
      type: 'flood',
      lon: 0.75,
      lat: 0.25,
      alt: null,
      weight: 1,
      tags: null,
      risk_level: 2,
    },
  ],
};

const RISK_EVALUATE_RESPONSE = {
  results: [
    {
      poi_id: E2E_RISK_POI_IDS[0],
      level: 4,
      score: 0.9,
      factors: [
        {
          id: 'rain',
          value: 10,
          score: 0.9,
          weight: 1,
          normalized_weight: 1,
          contribution: 0.9,
        },
      ],
      reasons: [
        {
          factor_id: 'rain',
          factor_name: '降雨',
          value: 10,
          threshold: 5,
          contribution: 0.9,
        },
      ],
    },
    {
      poi_id: E2E_RISK_POI_IDS[1],
      level: 2,
      score: 0.7,
      factors: [
        {
          id: 'wind',
          value: 6,
          score: 0.7,
          weight: 1,
          normalized_weight: 1,
          contribution: 0.7,
        },
      ],
      reasons: [
        {
          factor_id: 'wind',
          factor_name: '风',
          value: 6,
          threshold: 4,
          contribution: 0.7,
        },
      ],
    },
  ],
  summary: {
    total: 2,
    duration_ms: 8,
    max_level: 4,
    avg_score: 0.8,
    level_counts: { '4': 1, '2': 1 },
    reasons: { e2e: 2 },
  },
};

const EFFECT_PRESETS_RESPONSE = [
  {
    id: 'e2e-debris-flow',
    effect_type: 'debris_flow',
    intensity: 1,
    duration: 2,
    color_hint: 'rgba(255, 51, 0, 0.9)',
    spawn_rate: 40,
    particle_size: { min: 1, max: 3 },
    wind_influence: 0.2,
    risk_level: 'high',
  },
];

function fulfillJson(route: Route, data: unknown) {
  return route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(data),
  });
}

export async function installE2eMocks(page: Page, apiBaseUrl: string) {
  await page.route('**/config.json', async (route) =>
    fulfillJson(route, { apiBaseUrl }),
  );

  await page.route('**/api/v1/products', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, PRODUCTS_RESPONSE);
  });

  await page.route('**/api/v1/products/*', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, PRODUCT_DETAIL_RESPONSE);
  });

  await page.route('**/api/v1/risk/pois**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, RISK_POIS_RESPONSE);
  });

  await page.route('**/api/v1/risk/evaluate', async (route) => {
    if (route.request().method() !== 'POST') return route.fallback();
    return fulfillJson(route, RISK_EVALUATE_RESPONSE);
  });

  await page.route('**/api/v1/effects/presets', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, EFFECT_PRESETS_RESPONSE);
  });

  await page.route('**/api/v1/vector/**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, { u: [], v: [], lat: [], lon: [] });
  });

  await page.route('**/api/v1/vectors/**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return fulfillJson(route, { u: [], v: [], lat: [], lon: [] });
  });

  await page.route('**/api/v1/tiles/**', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: 'image/png',
      body: Buffer.from(ONE_BY_ONE_PNG_BASE64, 'base64'),
    });
  });
}
