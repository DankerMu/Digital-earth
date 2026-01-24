import { expect, test } from '@playwright/test';

import { E2E_PRODUCT_ID, E2E_RISK_POI_IDS, installE2eMocks } from './mocks';

function isTruthyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

test.describe('Core workflows', () => {
  test.beforeEach(async ({ page }, testInfo) => {
    const baseURL = testInfo.project.use.baseURL;
    if (!isTruthyString(baseURL)) {
      throw new Error('Missing baseURL in Playwright config');
    }

    await installE2eMocks(page, baseURL);
  });

  test('Flow A: 点位->仰视->锁层->层全局', async ({ page }, testInfo) => {
    await test.step('Open app', async () => {
      await page.goto('/');
      await expect(page.getByTestId('cesium-container')).toBeVisible();
    });

    await test.step('Enter Local mode (double click)', async () => {
      const canvas = page.locator('[data-testid="cesium-container"] canvas').first();
      await expect(canvas).toBeVisible();
      await canvas.click({ modifiers: ['Control'], force: true });
      await expect(page.getByTestId('local-info-panel')).toBeVisible();
      await expect(page.getByTestId('view-mode-indicator')).toHaveAttribute('data-view-mode', 'local');
    });

    await test.step('Switch camera perspective to upward (仰视)', async () => {
      const upward = page.getByTestId('camera-perspective-upward');
      await upward.click();
      await expect(upward).toHaveAttribute('aria-pressed', 'true');
    });

    await test.step('Lock current layer (锁定当前层)', async () => {
      await page.getByTestId('local-lock-layer').click();
      await expect(page.getByTestId('view-mode-indicator')).toHaveAttribute('data-view-mode', 'layerGlobal');
    });

    await test.step('Verify layer-global shell active', async () => {
      await expect
        .poll(() =>
          page.evaluate(() => {
            return window.__DIGITAL_EARTH_E2E__?.isLayerGlobalShellActive?.() ?? false;
          }),
        )
        .toBe(true);
    });

    await test.step('Screenshot', async () => {
      await testInfo.attach('flow-a', {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
    });
  });

  test('Flow B: 事件->风险点->特效触发', async ({ page }, testInfo) => {
    await test.step('Open app', async () => {
      await page.goto('/');
      await expect(page.getByTestId('cesium-container')).toBeVisible();
    });

    await test.step('Select event', async () => {
      await page.getByRole('button', { name: '展开信息面板' }).click();
      const eventItem = page.getByTestId(`event-item-${E2E_PRODUCT_ID}`);
      await expect(eventItem).toBeVisible();
      await eventItem.click();
      await expect(page.getByTestId('view-mode-indicator')).toHaveAttribute('data-view-mode', 'event');
    });

    await test.step('Verify polygon rendered', async () => {
      await expect
        .poll(() =>
          page.evaluate(() => window.__DIGITAL_EARTH_E2E__?.getEventEntityIds?.()?.length ?? 0),
        )
        .toBeGreaterThan(0);
    });

    await test.step('Verify risk POIs loaded', async () => {
      await expect
        .poll(() =>
          page.evaluate(() => window.__DIGITAL_EARTH_E2E__?.getRiskPoiIds?.()?.length ?? 0),
        )
        .toBeGreaterThan(0);
    });

    await test.step('Click risk POI on canvas', async () => {
      const poiId = E2E_RISK_POI_IDS[0];
      const canvas = page.locator('[data-testid="cesium-container"] canvas').first();
      await expect(canvas).toBeVisible();

      await expect
        .poll(() =>
          page.evaluate((id) => window.__DIGITAL_EARTH_E2E__?.getRiskPoiCanvasPosition?.(id) ?? null, poiId),
        )
        .not.toBeNull();

      const pos = await page.evaluate(
        (id) => window.__DIGITAL_EARTH_E2E__?.getRiskPoiCanvasPosition?.(id) ?? null,
        poiId,
      );
      if (!pos) {
        throw new Error('Risk POI canvas position unavailable');
      }

      await canvas.click({ position: pos, force: true });
      await expect(page.getByTestId('risk-poi-popup')).toBeVisible();
    });

    await test.step('Trigger disaster effect', async () => {
      await page.getByTestId('risk-open-disaster-demo').click();
      const dialog = page.getByRole('dialog', { name: '灾害演示' });
      await expect(dialog).toBeVisible();

      const playButton = dialog.getByRole('button', { name: '播放' });
      await expect(playButton).toBeEnabled();
      await playButton.click();

      await expect(page.locator('#effect-stage canvas[aria-label="effect-canvas"]')).toBeVisible();
    });

    await test.step('Screenshot', async () => {
      await testInfo.attach('flow-b', {
        body: await page.screenshot({ fullPage: true }),
        contentType: 'image/png',
      });
    });
  });
});
