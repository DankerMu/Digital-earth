# 技术手册（Digital Earth）

> 面向：开发/数据/运维同学  
> 目标：说明系统架构、数据流、关键模块与生产级配置要点。  
> 说明：本文以当前仓库为准，示例路径均为真实文件路径（可直接在仓库中打开）。

---

## 1. 架构概述

### 1.1 组件与职责

- **Web 前端（CesiumJS）**：`apps/web/`
  - 负责 3D 地球渲染、图层叠加、四种视图模式、体素云（VOLP）渲染、性能自适应
- **API 服务（FastAPI）**：`apps/api/`
  - 负责 Catalog、Tiles、Vector（风场）、Products、Risk、Effects、Volume 等业务 API（统一前缀 `/api/v1`，见 `CLAUDE.md`）
- **数据处理管线（Data Pipeline）**：`services/data-pipeline/`
  - 负责数据下载/解码、DataCube（NetCDF/Zarr）写入、瓦片生成、体数据导出、统计指标计算等离线/批处理
- **统一配置包**：`packages/config/`
  - 负责从 `config/<env>.json` + 环境变量加载配置，并强制校验“secrets 不入库”
- **共享领域模型/规则**：`packages/shared/`
  - 风险规则、图例、特效预设等 schema 与加载逻辑
- **部署与基础设施**
  - Docker/Compose：`deploy/`
  - Kubernetes：`infra/k8s/`

### 1.2 系统架构图（ASCII）

```
                         ┌──────────────────────────────┐
                         │          Web 前端             │
                         │  apps/web (CesiumJS/TS)       │
                         └───────────────┬──────────────┘
                                         │  HTTPS / REST
                                         │  /api/v1/*
                              ┌──────────▼───────────┐
                              │ 网关 / Ingress / CDN   │
                              │ Nginx / K8s Ingress    │
                              └──────────┬───────────┘
                                         │
                         ┌───────────────▼──────────────┐
                         │          API 服务             │
                         │ apps/api (FastAPI + uvicorn)  │
                         └───────┬─────────┬────────────┘
                                 │         │
                                 │         │
                           ┌─────▼───┐  ┌──▼───────────┐
                           │  Redis  │  │ PostgreSQL     │
                           │ 缓存/限流 │  │ Catalog/Products│
                           └─────┬───┘  └──┬───────────┘
                                 │         │
                                 │         │
                ┌────────────────▼───┐  ┌──▼──────────────────────┐
                │ 对象存储/静态托管   │  │ 本地数据（开发/离线）     │
                │ S3/MinIO/CDN        │  │ Data/*（CLDAS/ECMWF/...） │
                └─────────┬──────────┘  └───────────┬─────────────┘
                          │                           │
                          │                           │
                   ┌──────▼───────────────────────────▼──────┐
                   │           Data Pipeline（离线）           │
                   │ services/data-pipeline (xarray/ecCodes)   │
                   └──────────────────────────────────────────┘
```

### 1.3 数据流（从数据源到渲染）

> 当前仓库对“远程数据源”的支持以离线管线为主；API 中的 `RemoteDataSource` 仍处于未实现状态（见 `services/data-pipeline/src/data_source.py`）。

- **CLDAS（本地模式）**
  1. 数据落盘到 `Data/CLDAS/`（默认；可通过 `config/local-data.yaml` 与 `DIGITAL_EARTH_LOCAL_DATA_*` 覆盖）
  2. API 通过 `LocalDataSource` 建立索引（缓存：`.cache/local-data-index.json`）
  3. Web 图层（如温度/云/降水）调用：
     - `GET /api/v1/catalog/cldas/times` 获取可用时次
     - `GET /api/v1/tiles/cldas/{time_key}/{var}/{z}/{x}/{y}.png` 实时切片

- **ECMWF（离线生产 + Catalog 索引）**
  1. 管线下载 GRIB2（`services/data-pipeline/src/ecmwf/downloader.py`）
  2. 解码/加工为 DataCube（NetCDF/Zarr，`services/data-pipeline/src/datacube/storage.py`）
  3. 生成 raster tiles 并上传对象存储（`services/data-pipeline/src/tiles/generate.py` + `services/data-pipeline/src/tiling/storage.py`）
  4. Catalog 数据（run/time/asset 元数据）写入 Postgres（表结构见 `apps/api/src/models/catalog.py`，迁移见 `apps/api/migrations/`）
  5. Web 侧通过 Catalog/Vector/Tiles API 拉取渲染数据

- **Volume（体素云）**
  1. 离线导出 per-level 体数据切片（NetCDF/Zarr）：`services/data-pipeline/src/volume/cloud_density.py`
  2. API 读取 `DIGITAL_EARTH_VOLUME_DATA_DIR` 下的切片并编码为 VOLP：`apps/api/src/routes/volume.py` + `services/data-pipeline/src/volume/pack.py`
  3. Web 解码 VOLP 并进行 ray-march 渲染：`apps/web/src/lib/volumePack.ts` + `apps/web/src/features/voxelCloud/*`

### 1.4 配置管理（生产级约束）

#### 1) JSON 配置（非 secret）

- 必备：`config/dev.json`、`config/staging.json`、`config/prod.json`
- 加载逻辑：`packages/config/src/digital_earth_config/settings.py`
  - 通过 `DIGITAL_EARTH_ENV` 选择 env
  - 通过 `DIGITAL_EARTH_CONFIG_DIR` 指定配置目录（否则自动向上搜索包含三份 JSON 的 `config/`）

#### 2) Secrets（环境变量注入）

**禁止写入 `config/*.json` 的敏感项**（会触发强校验拒绝启动）：

- 数据库：`DIGITAL_EARTH_DB_USER`、`DIGITAL_EARTH_DB_PASSWORD`
- Redis：`DIGITAL_EARTH_REDIS_PASSWORD`
- ECMWF：`DIGITAL_EARTH_PIPELINE_ECMWF_API_KEY`
- Cesium：`DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN`（规范与轮换见 `docs/cesium-token-security.md`）
- 对象存储：`DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID`、`DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY`

---

## 2. 数据管线

### 2.1 ECMWF 数据获取与处理

#### 数据源与配置

- 典型数据格式：**GRIB2**
- ECMWF 变量/层配置：`services/data-pipeline/config/ecmwf_variables.yaml`
  - 解析与校验：`services/data-pipeline/src/ecmwf/config.py`
  - 示例：地面变量 `2t/10u/10v/tp/ptype/tcc`，气压层 `t/u/v/r/gh`（850/700/500/300 hPa）

#### 下载器（断点续传/校验/清单）

- 实现：`services/data-pipeline/src/ecmwf/downloader.py`
- 特点（面向生产）：
  - retry（429/5xx/timeout 等）
  - Range 断点续传
  - 可选 size/hash 校验
  - 输出 manifest/report（便于审计与排障）

#### DataCube 存储（NetCDF/Zarr）

- 读写实现：`services/data-pipeline/src/datacube/storage.py`
  - `write_datacube()`：NetCDF（h5netcdf/gzip）或 Zarr（zstd/lz4/zlib）
  - `open_datacube()`：API/管线共用的读取入口

#### Raster Tiles 生成

- CLI 入口：`services/data-pipeline/src/tiles/__main__.py`（即 `python -m tiles`）
- 主要实现：`services/data-pipeline/src/tiles/generate.py`
- 典型用法（示例）：

```bash
# 在 services/data-pipeline/ 目录下执行
python -m tiles \
  --datacube /path/to/datacube.nc \
  --output-dir /tmp/tiles-out \
  --valid-time 2026-01-01T00:00:00Z \
  --level sfc \
  --temperature --cloud --precipitation \
  --format png --format webp
```

> CRS/zoom 策略统一见 `docs/tiling-strategy.md` 与 `config/tiling.yaml`。

### 2.2 CLDAS 数据接入

#### 本地数据目录与索引

- local-data 配置：`config/local-data.yaml`（schema v1）
- 解析逻辑：`packages/config/src/digital_earth_config/local_data.py`
- 数据索引/缓存：
  - 索引器：`services/data-pipeline/src/local/indexer.py`
  - 缓存文件（默认）：`.cache/local-data-index.json`

默认目录布局（可在 `config/local-data.yaml` 中调整）：

```
Data/
├── CLDAS/                      # CLDAS NetCDF
├── EC-forecast/EC预报/          # ECMWF（本地导出/缓存）
└── 城镇预报导出/                 # Town forecast 文件
```

#### CLDAS 文件命名约束

- 解析器：`services/data-pipeline/src/local/cldas_loader.py`
- 约定（示例）：`CHINA_WEST_<resolution>_HOR-<VAR>-<YYYYMMDDHH>.nc`

#### API 接口关联

- `GET /api/v1/local-data/index`：列出本地数据索引（可按 kind 过滤）
- `GET /api/v1/catalog/cldas/times`：CLDAS 可用时次（支持按变量过滤）
- `GET /api/v1/tiles/cldas/{time_key}/{var}/{z}/{x}/{y}.png`：实时切片（见 `apps/api/src/routers/tiles.py`）

### 2.3 瓦片生成流程

#### CRS/Zoom 统一

- 统一 CRS：`EPSG:4326`
- Zoom 策略与变更原则：`docs/tiling-strategy.md`
- 配置文件：`config/tiling.yaml`（加载入口：`services/data-pipeline/src/tiling/config.py`）

#### Tile 生成器与 Legend

- CLDAS 即时切片：`services/data-pipeline/src/tiling/cldas_tiles.py`
- ECMWF raster tiling：`services/data-pipeline/src/tiling/*_tiles.py`
  - 温度：`tiling/temperature_tiles.py`
  - 云量：`tiling/tcc_tiles.py`
  - 降水：`tiling/precip_amount_tiles.py`
  - 偏差（forecast vs obs）：`tiling/bias_tiles.py`
- Legend：
  - 默认：`config/legend.json` / `packages/config/src/legends/*.json`
  - API 输出：`apps/api/src/routers/legends.py` + `apps/api/src/legend_config.py`

#### Tiles API（对象存储/本地目录）

- 入口：`apps/api/src/routers/tiles.py`
- 两种工作方式：
  1. **redirect（默认）**：`GET /api/v1/tiles/{tile_path}?redirect=true` → 302 到对象存储 URL（适合 CDN）
  2. **proxy**：`redirect=false` 时由 API 直出 bytes（可附加 gzip/webp 协商）
- 存储配置（满足任一即可）：
  - `DIGITAL_EARTH_STORAGE_TILES_BASE_URL`（优先，直接拼 URL）
  - 或 `DIGITAL_EARTH_STORAGE_ENDPOINT_URL` +（可选）AK/SK（可签名 URL 或直接拼 bucket/key）
  - 或 `DIGITAL_EARTH_STORAGE_TILES_DIR`（本地目录直读；适合开发/离线）

#### 网关缓存（Nginx）

- 配置：`deploy/nginx/sites-enabled/app.conf`
  - 对 `/api/v1/tiles/` 启用 `proxy_cache`，默认 `proxy_cache_valid 200 1h`
  - 避免缓存 trace id：对上游 `X-Trace-Id` 做 `proxy_hide_header`，再为每次请求生成新 `X-Trace-Id`

### 2.4 Volume API 云体数据（VOLP）

#### VOLP 格式

- 格式定义：`docs/volume-pack.md`
- 参考实现：
  - Python encoder：`services/data-pipeline/src/volume/pack.py`
  - TS decoder：`apps/web/src/lib/volumePack.ts`

#### Volume API（服务端约束）

- 路由实现：`apps/api/src/routes/volume.py`
- 入口：`GET /api/v1/volume`
- 关键限制（用于抗滥用/防 DoS）：
  - bbox 最大面积：`MAX_BBOX_AREA_DEG2`
  - 最小分辨率：`MIN_RES_METERS`
  - 输出大小上限：`MAX_OUTPUT_BYTES`
  - 可缓存上限：`MAX_CACHEABLE_BYTES`（Redis）

#### 体数据目录布局（必读）

Volume API 读取 `DIGITAL_EARTH_VOLUME_DATA_DIR` 指向的目录；未配置会返回 503：

```
<DIGITAL_EARTH_VOLUME_DATA_DIR>/
└── ecmwf/cloud_density/                # layer（默认，见 DEFAULT_CLOUD_DENSITY_LAYER）
    └── 20260101T000000Z/               # time_key
        ├── 1000.nc                     # level_key（或 1000.zarr）
        ├── 925.nc
        ├── ...
        └── manifest.json               # 可选（导出器可写）
```

对应导出器：`services/data-pipeline/src/volume/cloud_density.py`

---

## 3. 后端服务

> API 统一前缀：`/api/v1`；应用入口：`apps/api/src/main.py`。

### 3.1 Catalog API

- 路由：`apps/api/src/routers/catalog.py`
- 依赖：
  - Postgres：`apps/api/src/models/catalog.py`（ECMWF run/time 索引）
  - Redis：`apps/api/src/catalog_cache.py`（stale-while-revalidate 模式）
- 典型接口：
  - `GET /api/v1/catalog/ecmwf/runs`
  - `GET /api/v1/catalog/ecmwf/runs/{run}/times`
  - `GET /api/v1/catalog/ecmwf/runs/{run}/vars`
  - `GET /api/v1/catalog/cldas/times`

### 3.2 Tiles API

- 路由：`apps/api/src/routers/tiles.py`
- 两类 tiles：
  - **CLDAS 即时 tiles**：`/api/v1/tiles/cldas/...`（从本地 NetCDF 读 → 插值 → PNG）
  - **存储 tiles**：`/api/v1/tiles/{tile_path}`（本地目录 / 对象存储 / 302 redirect）

### 3.3 Vector API（风场）

- 路由：`apps/api/src/routers/vector.py`
- 典型接口：
  - `GET /api/v1/vector/ecmwf/{run}/wind/{level}/{time}`
  - `POST /api/v1/vector/ecmwf/{run}/wind/{level}/{time}/prewarm`
  - `GET /api/v1/vector/ecmwf/{run}/wind/{level}/{time}/streamlines`
- 缓存：
  - Redis：Catalog cache（热数据）
  - 文件缓存：`DIGITAL_EARTH_VECTOR_CACHE_DIR`（风场/流线计算结果落盘，减少重复计算）

### 3.4 Products API（事件/产品）

- 路由：`apps/api/src/routers/products.py`
- 编辑接口保护：
  - 中间件：`apps/api/src/editor_permissions.py`
  - 开关：`ENABLE_EDITOR=true`
  - Token：`EDITOR_TOKEN`（Header `Authorization: Bearer <token>` 或 `X-Editor-Token`）
- 典型接口：
  - `GET /api/v1/products`
  - `GET /api/v1/products/{product_id}`
  - `POST /api/v1/products/{product_id}/publish`

### 3.5 Risk API

- 路由：`apps/api/src/routers/risk.py`
- 配置：
  - 规则：`config/risk-rules.yaml`（可用 `DIGITAL_EARTH_RISK_RULES_CONFIG` 覆盖）
  - 强度映射：`config/risk-intensity.yaml`（可用 `DIGITAL_EARTH_RISK_INTENSITY_CONFIG` 覆盖）
- 典型接口：
  - `POST /api/v1/risk/evaluate`
  - `GET /api/v1/risk/pois` / `GET /api/v1/risk/pois/cluster`
  - `GET /api/v1/risk/rules` / `POST /api/v1/risk/rules/evaluate`

### 3.6 Effects API

- 路由：`apps/api/src/routers/effects.py`
- 预设配置：
  - 默认：`packages/shared/config/effect_presets.yaml`
  - 覆盖：`DIGITAL_EARTH_EFFECT_PRESETS_CONFIG`
- 典型接口：
  - `GET /api/v1/effects/presets`
  - `POST /api/v1/effects/trigger-logs`（触发记录，受采样率控制：`settings.api.effect_trigger_logging`）

### 3.7 Volume API

- 路由：`apps/api/src/routes/volume.py`
- 入口：`GET /api/v1/volume`
- 数据读取：`services/data-pipeline/src/datacube/storage.py`（读取 NetCDF/Zarr）
- 编码：`services/data-pipeline/src/volume/pack.py`（输出 VOLP）

---

## 4. 前端架构

### 4.1 状态管理（Store / Zustand 迁移友好）

项目当前采用 `useSyncExternalStore` 实现轻量 store（形式上与 Zustand store 接近，方便后续迁移）：

- 目录：`apps/web/src/state/`
- 特点：
  - 单文件一个 store（具备 `getState/setState/subscribe`）
  - 多数 store 通过 `localStorage` 持久化（容错读写）

关键 store 示例：

- 视图模式：`apps/web/src/state/viewMode.ts`
- 时间轴：`apps/web/src/state/time.ts`
- 图层管理：`apps/web/src/state/layerManager.ts`
- 性能模式：`apps/web/src/state/performanceMode.ts`

> `docs/dev-spec.md` 推荐“全局状态用 Zustand”。如要迁移，可保持 store selector API 不变，将内部实现替换为 Zustand `create()`。

### 4.2 视图模式（Global/Local/Event/LayerGlobal）

- 定义与路由状态：`apps/web/src/state/viewMode.ts`
- 要点：
  - 支持前进/后退历史栈（`history`），并持久化保存最近 Local/Event/LayerGlobal 的参数
  - 入口交互可参考用户指南：`docs/user-guide.md`

### 4.3 图层系统

核心组成：

- 图层状态：`apps/web/src/state/layerManager.ts`
  - 同类型图层互斥可见（例如温度图层一次只显示一个）
- 图层实现：`apps/web/src/features/layers/*Layer.ts`
  - 基于 Cesium `ImageryLayer` + `UrlTemplateImageryProvider`
  - 示例：`apps/web/src/features/layers/TemperatureLayer.ts`
- 请求优化：
  - 预取与缓存：`apps/web/src/features/layers/tilePrefetch.ts`
  - 在低性能/弱网/Save-Data 模式下自动关闭预取（与 `apps/web/src/state/performanceMode.ts` 联动）

### 4.4 体素云渲染（VOLP + Ray-marching）

- PoC 报告：`docs/voxel-cloud-poc-report.md`
- 核心模块：
  - 渲染器：`apps/web/src/features/voxelCloud/VoxelCloudRenderer.ts`
  - Shader：`apps/web/src/features/voxelCloud/shader.ts`
  - VOLP 解码：`apps/web/src/lib/volumePack.ts`
  - 质量/自适应：`apps/web/src/features/voxelCloud/qualityConfig.ts` + `apps/web/src/state/performanceMode.ts`
- Demo 数据生成：

```bash
pnpm -C apps/web generate:voxel-cloud-demo
```

---

## 5. 性能优化

### 5.1 缓存策略

- **HTTP 缓存（ETag/Cache-Control）**
  - Catalog/Tiles 等多接口返回 ETag（例如 `apps/api/src/routers/catalog.py`、`apps/api/src/routers/tiles.py`）
- **Redis 缓存**
  - Catalog：`apps/api/src/catalog_cache.py`（fresh/stale + lock）
  - Volume：`apps/api/src/routes/volume.py`（TTL 来自 `settings.api.volume_cache_ttl_seconds`）
- **网关缓存**
  - Nginx tiles cache：`deploy/nginx/sites-enabled/app.conf`
- **客户端预取**
  - `apps/web/src/features/layers/tilePrefetch.ts`：按帧缓存 URL、限制并发、错误 cooldown、性能模式联动

### 5.2 限流机制

- API 限流中间件：`apps/api/src/rate_limit.py`
  - Redis ZSET + Sliding Window（Lua）
  - 默认规则定义：`packages/config/src/digital_earth_config/settings.py`（`_default_api_rate_limit_rules()`）
  - 支持 allowlist/blocklist/trusted proxies（适配 Ingress/Nginx）
- 编辑接口额外保护：`apps/api/src/editor_permissions.py`

### 5.3 LOD 自动降级

- 前端性能模式：`apps/web/src/state/performanceMode.ts`
  - `mode=low` 时关闭 tile 预取、降低体素云质量、减少高消耗效果
  - `autoDowngrade=true` 时基于帧率/压力自动降级（实现与阈值见体素云模块与 viewer 监控代码）

---

## 6. 安全配置

### 6.1 Token 安全

- Web Cesium ion Token：`docs/cesium-token-security.md`
  - 强制最小权限 + Allowed URLs + 资产白名单
  - 通过 `DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN` 注入（生产不入库）
- UE Token（如需）：`infra/k8s/secrets/README.md`、`docs/ue-token-security.md`
- 编辑接口 Token：
  - 开启：`ENABLE_EDITOR=true`
  - 注入：`EDITOR_TOKEN=<token>`（仅用于写接口；读接口保持公开）

### 6.2 WAF 规则（K8s）

- 说明文档：`docs/waf-configuration.md`
- 规则 ConfigMap：`infra/k8s/waf-rules.yaml`
- Nginx Ingress 示例：`infra/k8s/ingress/nginx/digital-earth-ingress.yaml`
- 自检脚本：`scripts/waf-smoke-test.sh`

### 6.3 限流策略（建议基线）

- 代码默认（可作为基线）：
  - `/api/v1/tiles`：300 rpm
  - `/api/v1/vector`：60 rpm
  - `/api/v1/volume`：10 rpm
  - `/api/v1/errors`：10 rpm
  - 见 `packages/config/src/digital_earth_config/settings.py`
- 生产建议：
  - 配合边缘限流/封禁（Ingress/WAF）
  - 对高成本接口（Volume/Streamlines）做更严格阈值与更小 cacheable 上限

---

## 参考文档

- 项目约束：`CLAUDE.md`
- 开发规范：`docs/dev-spec.md`
- UI 规范：`docs/ui-design-spec.md`
- 运维手册：`docs/ops-manual.md`
- 用户指南：`docs/user-guide.md`
- 瓦片策略：`docs/tiling-strategy.md`
- VOLP 格式：`docs/volume-pack.md`
