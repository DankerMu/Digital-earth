# [ST-0025] 自建底图/地形上线切换方案（设计）

更新时间：2026-01-20

## 背景与目标

当前 Web 端可能在部分环境依赖 Cesium ion（例如 World Terrain/部分资产）。出于成本、可控性与合规性考虑，需要在必要时将 **底图/地形** 平滑切换到自建服务，并具备快速回滚能力。

目标：
- 在不改代码/不重新构建前端的情况下，通过 **运行时配置开关** 切换 `ion ↔ 自建`
- 灰度发布：支持按环境/域名/配置中心逐步放量
- 回滚：一键回到上一套 provider（秒级生效，刷新页面即可）
- 提供缓存/CDN 建议，降低自建服务压力与延迟

非目标：
- 本文不覆盖具体“自建瓦片生产”细节（由 ST-0023 / ST-0024 / ST-0025 的其他子任务覆盖）

---

## 设计概览

### 1) Provider 抽象（客户端）

将底图与地形的来源统一抽象为 Provider，由运行时配置决定：

- `basemapProvider`: `open | ion | selfHosted`
- `terrainProvider`: `none | ion | selfHosted`

Web 端实现方式：
- 继续保留现有开源底图（`open`）的 `BasemapSelector`
- 当 `basemapProvider != open` 时，隐藏底图选择器，避免“看起来能切换但实际无效”的误用
- `ion` 模式：通过 `Ion.defaultAccessToken` + `createWorldImageryAsync()` / `createWorldTerrainAsync()` 加载
- `selfHosted` 模式：
  - 底图：`UrlTemplateImageryProvider(urlTemplate)`
  - 地形：`CesiumTerrainProvider.fromUrl(terrainUrl)`（quantized-mesh）

### 2) 运行时配置开关（无重建）

Web 端通过 `GET /config.json` 获取运行时配置（当前项目已采用该方式提供 `apiBaseUrl`）。

新增字段（示例）：

```json
{
  "apiBaseUrl": "https://api.digital-earth.example",
  "map": {
    "basemapProvider": "ion",
    "terrainProvider": "ion",
    "cesiumIonAccessToken": "<runtime-injected-token>",
    "selfHosted": {
      "basemapUrlTemplate": "https://tiles.digital-earth.example/basemap/{z}/{x}/{y}.jpg",
      "terrainUrl": "https://tiles.digital-earth.example/terrain/"
    }
  }
}
```

建议：
- `config.json` 不入库真实 token；生产通过挂载文件/配置中心/渲染模板注入
- 只在需要 ion 时提供 `cesiumIonAccessToken`

---

## 灰度切换与回滚策略

### 推荐灰度流程

1. **双轨并行**：提前上线自建 tiles 服务（CDN 前置），并保证 ion 仍可用
2. **Canary 环境验证**：仅 staging/少量测试域名 `basemapProvider=selfHosted`
3. **小流量放量**：按环境/域名分组逐步切换
4. **全量切换**：确认稳定后全量切换

### 回滚策略（P0）

回滚开关只需要将 `config.json` 中的 provider 改回 `ion`（或 `open`）并刷新页面：
- 不需要回滚前端代码
- 不需要重新构建
- 若自建服务出现 5xx/延迟显著升高，可快速回退

---

## CDN/缓存建议（自建）

### 1) URL 版本化（强缓存前提）
- 通过路径版本或查询参数区分版本：`/terrain/v1/...`、`/basemap/v1/...`
- 发布新版本时切换版本前缀，避免旧缓存污染

### 2) 缓存头
- 静态瓦片：`Cache-Control: public, max-age=31536000, immutable`
- `tileset.json` / `layer.json` 等元数据：`max-age=60~300`（便于快速切换/回滚）

### 3) CDN 配置
- 开启 Range 支持（部分地形/3D 数据可能受益）
- gzip/br（JSON/元数据），图片/地形二进制按类型选择
- 关注热点区域（北京/重点区域）预热与回源保护

---

## 客户端实现要点（落地）

- `apps/web/src/config.ts`：扩展 `PublicConfig.map` 并保持向后兼容（旧 `config.json` 仍可用）
- `apps/web/src/features/viewer/CesiumViewer.tsx`：根据 `map.*Provider` 应用 imagery/terrain provider
- 支持 `open` 模式下继续使用现有开源底图切换逻辑
