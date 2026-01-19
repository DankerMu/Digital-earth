# [ST-0024] 开源影像底图接入 PoC（WMTS/TMS）评估报告

更新时间：2026-01-19

## 背景

目标是在不依赖 Cesium ion 的情况下，接入可用的开源影像底图，并在 CesiumJS 中验证可显示、可切换、切换流畅，同时评估清晰度/稳定性/延迟。

## PoC 结论（建议）

- **默认底图**：Sentinel-2 Cloudless（EOX，URL Template/XYZ）
- **备用底图**：NASA GIBS Blue Marble（WMTS）
- 两者均无需 token，符合“不依赖 Cesium ion”的目标。

## 接入实现概览

- 配置：`apps/web/src/config/basemaps.ts`
  - `nasa-gibs-blue-marble`（WMTS）
  - `s2cloudless-2021`（URL Template/XYZ）
- Cesium ImageryProvider 适配：`apps/web/src/features/viewer/cesiumBasemap.ts`
  - `WebMapTileServiceImageryProvider`（WMTS）
  - `UrlTemplateImageryProvider`（TMS/XYZ，支持 `reverseY` 规范化）
- 选择器 UI：`apps/web/src/features/viewer/BasemapSelector.tsx`
  - 通过 `localStorage` 持久化：`apps/web/src/state/basemap.ts`

## 验证方式

1. 启动：`pnpm --filter web dev`
2. 打开页面后，在左上角 **“底图”** 下拉框切换：
   - Sentinel-2 Cloudless（EOX）
   - NASA GIBS（Blue Marble）
3. 验证点：
   - 底图可显示（不出现空白/404）
   - 切换后即时生效（`requestRenderMode` 下仍能触发渲染）
   - 多次切换无崩溃、无明显卡顿

## 服务信息

### NASA GIBS（WMTS）

- WMTS Endpoint（EPSG:3857）：`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi`
- Layer：`BlueMarble_NextGeneration`
- TileMatrixSet：`GoogleMapsCompatible_Level8`（最大 8 级）
- Cache：`cache-control: public, max-age=259200`（3 天）

### Sentinel-2 Cloudless（EOX，URL Template/XYZ）

- URL Template：`https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg`
- 最高缩放：配置为 `maximumLevel: 14`（更适合城市级别观察）
- Cache：`cache-control: max-age=604800`（7 天）

## 评估

### 1) 清晰度（主观 + 可解释指标）

- **S2 Cloudless**：最高到 `z=14`，对城市/道路轮廓更友好，适合作为默认影像底图。
- **GIBS Blue Marble**：最高到 `z=8`，适合全球/洲际视图；放大到城市级别会明显发糊，更适合作为备用或“全球概览”底图。

### 2) 稳定性（可用性/缓存/依赖）

- 两个源均为公网 HTTPS，**不依赖 token**。
- 关键瓦片请求在本次验证中均返回 `HTTP 200`，并带有合理缓存头（3 天/7 天）。
- 风险点：
  - 公网服务可能存在区域性抖动、限流、跨境链路波动；生产环境建议加入 CDN/代理或做多源 fallback。

### 3) 延迟（本机网络快速采样）

说明：下表为使用 `curl` 在本机网络环境下对单个瓦片进行 3 次采样得到的 `TTFB/total` 量级（仅用于 PoC 对比，不代表生产真实用户）。

#### NASA GIBS Blue Marble（WMTS）

- z0（0/0/0）：TTFB ~0.84–1.20s，约 12.9KB
- z8（北京附近 210/97）：TTFB ~0.84–0.89s，约 10.6KB

#### EOX S2 Cloudless（URL Template/XYZ）

- z0（0/0/0）：TTFB ~1.22–3.88s（首包可能更慢），约 11.1KB
- z12（北京附近 3372/1552）：TTFB ~0.94–1.27s，约 20.6KB
- z14（北京附近 13489/6208）：TTFB ~1.20–1.26s，约 12.7KB

## 建议的下一步

- 增加“影像底图可用性检测/自动降级”（例如请求失败时自动切换到备用底图）。
- 统一 attribution/credit 展示策略，确保底图来源清晰可见（尤其是对外发布时）。
- 如需要更“最新”的 NASA 真彩影像，可再评估引入带 Time 维度的 GIBS 图层，并设计稳定的时间选择/回退策略。

