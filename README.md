# Digital Earth（数字地球气象可视化平台）

Digital Earth 是一个面向 **气象数据可视化** 的 3D 地球平台：在浏览器中基于 CesiumJS 渲染全球场景，并通过 FastAPI 提供统一的气象数据服务（瓦片、风场、风险、特效、体数据等）。

## 项目简介

**核心能力**

- **3D 地球气象可视化**：温度、云量、降水、风场、积雪等要素叠加渲染
- **四种视图模式**：Global / Local / Event / LayerGlobal（见 `apps/web/src/state/viewMode.ts`）
- **瓦片与体数据服务**：Raster tiles、风场矢量/流线、Volume（体素云 VOLP）
- **风险与事件产品**：风险点聚合、规则评估、事件/产品管理与发布
- **生产级运行特性**：缓存（ETag/Redis/Nginx）、限流（Redis Sliding Window）、WAF（K8s/Ingress）、归因与免责声明

> 归因与免责声明配置：`config/attribution.yaml`（API：`/api/v1/attribution`）。

## 技术栈

| 层级 | 选型 | 说明 |
|---|---|---|
| 前端 | CesiumJS + React + TypeScript + Vite + Tailwind CSS | 代码：`apps/web/` |
| 后端 | FastAPI + Python 3.11 + SQLAlchemy + Alembic | 代码：`apps/api/` |
| 数据处理 | xarray + (h5netcdf/h5py) + ecCodes（管线） | 代码：`services/data-pipeline/` |
| 存储/缓存 | PostgreSQL 15+ + Redis 7+ + S3/MinIO（可选） | 配置：`config/*.json` |
| 部署 | Docker + Kubernetes + Nginx/Ingress | 目录：`deploy/`、`infra/` |

## 快速开始

### 环境要求

- Node.js `20+`
- Python `3.11+`
- pnpm `9+`
- PostgreSQL `15+`
- Redis `7+`
- （可选）Docker `24+` / Docker Compose v2：用于快速启动 Postgres/Redis

### 克隆仓库

```bash
git clone <YOUR_REPO_URL>
cd Digital-earth
```

### 安装依赖（前端）

```bash
pnpm install
```

### 配置环境变量

本仓库提供模板：`.env.template`。推荐在仓库根目录创建 `.env`（已被 `.gitignore` 忽略），并在启动 API 前加载到当前 shell。

1) 创建 `.env`

```bash
cp .env.template .env
```

2) 填写（最小可运行配置）

> `DIGITAL_EARTH_DB_USER` / `DIGITAL_EARTH_DB_PASSWORD` 是 **启动 API 必需项**（见 `packages/config/src/digital_earth_config/settings.py` 的强校验）。

```bash
# 必需（本地开发最小集）
DIGITAL_EARTH_ENV=dev
DIGITAL_EARTH_CONFIG_DIR=./config
DIGITAL_EARTH_DB_USER=app
DIGITAL_EARTH_DB_PASSWORD=app_password

# 可选：Redis 设置了密码时再配置（不允许空字符串）
DIGITAL_EARTH_REDIS_PASSWORD=

# 可选：编辑接口开关（不开启则所有写接口禁用/按默认策略）
ENABLE_EDITOR=false
EDITOR_TOKEN=
```

3) 将 `.env` 加载到当前终端（zsh/bash）

```bash
set -a
source .env
set +a
```

#### 环境变量清单（常用）

下表列出项目启动/部署/安全相关的常用环境变量（含 `.env.template` 与常见覆盖项）。更完整的字段与校验逻辑请参考：

- `packages/config/src/digital_earth_config/settings.py`
- `packages/config/src/digital_earth_config/local_data.py`
- `docs/technical-manual.md`

| 变量 | 是否必需 | 说明 | 示例 |
|---|---:|---|---|
| `DIGITAL_EARTH_ENV` | 推荐 | 运行环境：`dev/staging/prod`（默认 `dev`） | `dev` |
| `DIGITAL_EARTH_CONFIG_DIR` | 推荐 | 配置目录（包含 `dev.json/staging.json/prod.json`） | `./config` |
| `DIGITAL_EARTH_API_CORS_ORIGINS` | 否 | CORS 白名单（字符串逗号分隔或 JSON 数组） | `http://localhost:3000` |
| `DIGITAL_EARTH_DB_HOST` | 否 | Postgres host（覆盖 `config/<env>.json`） | `localhost` |
| `DIGITAL_EARTH_DB_PORT` | 否 | Postgres port | `5432` |
| `DIGITAL_EARTH_DB_NAME` | 否 | 数据库名 | `digital_earth` |
| `DIGITAL_EARTH_DB_USER` | 是 | Postgres 用户（禁止写入 `config/*.json`） | `app` |
| `DIGITAL_EARTH_DB_PASSWORD` | 是 | Postgres 密码（禁止写入 `config/*.json`） | `app_password` |
| `DIGITAL_EARTH_REDIS_HOST` | 否 | Redis host（覆盖 `config/<env>.json`） | `localhost` |
| `DIGITAL_EARTH_REDIS_PORT` | 否 | Redis port | `6379` |
| `DIGITAL_EARTH_REDIS_PASSWORD` | 否 | Redis 密码（如果设置，不能是空字符串） | `redis_password` |
| `DIGITAL_EARTH_PIPELINE_DATA_SOURCE` | 否 | 数据来源：`local/remote`（默认从 `config/<env>.json` 读取） | `local` |
| `DIGITAL_EARTH_PIPELINE_ECMWF_API_KEY` | 否 | ECMWF 访问密钥（remote 模式需要） | `<ECMWF_KEY>` |
| `DIGITAL_EARTH_LOCAL_DATA_CONFIG` | 否 | local-data 配置文件路径（默认 `config/local-data.yaml`） | `./config/local-data.yaml` |
| `DIGITAL_EARTH_LOCAL_DATA_ROOT` | 否 | 本地数据根目录（相对路径相对仓库根） | `Data` |
| `DIGITAL_EARTH_LOCAL_DATA_CLDAS_DIR` | 否 | CLDAS 子目录（相对 local-data root） | `CLDAS` |
| `DIGITAL_EARTH_LOCAL_DATA_ECMWF_DIR` | 否 | ECMWF 子目录（相对 local-data root） | `EC-forecast/EC预报` |
| `DIGITAL_EARTH_LOCAL_DATA_TOWN_FORECAST_DIR` | 否 | 城镇预报子目录（相对 local-data root） | `城镇预报导出` |
| `DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN` | 否 | Web Cesium ion token（遵循 `docs/cesium-token-security.md`） | `<ION_WEB_TOKEN>` |
| `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN` | 否 | UE Cesium ion token（见 `docs/ue-token-security.md`） | `<ION_UE_TOKEN>` |
| `DIGITAL_EARTH_ATTRIBUTION_CONFIG` | 否 | 归因配置文件路径（默认 `config/attribution.yaml`） | `./config/attribution.yaml` |
| `DIGITAL_EARTH_LEGENDS_DIR` | 否 | legend 目录（默认 `packages/config/src/legends/`） | `./packages/config/src/legends` |
| `DIGITAL_EARTH_EFFECT_PRESETS_CONFIG` | 否 | 特效预设 YAML（默认 `packages/shared/config/effect_presets.yaml`） | `./packages/shared/config/effect_presets.yaml` |
| `DIGITAL_EARTH_RISK_RULES_CONFIG` | 否 | 风险规则 YAML（默认 `config/risk-rules.yaml`） | `./config/risk-rules.yaml` |
| `DIGITAL_EARTH_RISK_INTENSITY_CONFIG` | 否 | 风险强度映射 YAML（默认 `config/risk-intensity.yaml`） | `./config/risk-intensity.yaml` |
| `DIGITAL_EARTH_TILING_CONFIG` | 否 | 切片策略 YAML（默认 `config/tiling.yaml`） | `./config/tiling.yaml` |
| `DIGITAL_EARTH_STORAGE_ENDPOINT_URL` | 否 | 对象存储 endpoint（S3/MinIO） | `http://minio:9000` |
| `DIGITAL_EARTH_STORAGE_REGION_NAME` | 否 | 对象存储 region | `us-east-1` |
| `DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID` | 否 | 对象存储 AK（与 SK 成对设置） | `<AK>` |
| `DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY` | 否 | 对象存储 SK（与 AK 成对设置） | `<SK>` |
| `DIGITAL_EARTH_STORAGE_TILES_BASE_URL` | 否 | tiles 的 HTTP base URL（优先于 endpoint 直拼） | `https://cdn.example/tiles` |
| `DIGITAL_EARTH_STORAGE_TILES_DIR` | 否 | 本地 tiles 目录（开发/离线直读） | `./Data/tiles` |
| `DIGITAL_EARTH_VOLUME_DATA_DIR` | 否 | Volume API 体数据目录（未配置则 `/api/v1/volume` 返回 503） | `./Data/volume` |
| `DIGITAL_EARTH_VECTOR_CACHE_DIR` | 否 | Vector API 文件缓存目录（风场/流线缓存） | `./.cache/vector` |
| `ENABLE_EDITOR` | 否 | 是否启用编辑接口鉴权（默认 false） | `true` |
| `EDITOR_TOKEN` | 否 | 编辑接口 Token（Header: `Authorization: Bearer <token>` 或 `X-Editor-Token`） | `<token>` |

> 配置文件（`config/<env>.json`）**禁止**包含 secrets：数据库账号/密码、Redis 密码、ECMWF key、Cesium token、对象存储 AK/SK 等；加载器会在 `packages/config/src/digital_earth_config/settings.py` 中强校验并拒绝启动。

### 启动依赖服务（Postgres/Redis）

#### 方式 A：使用 Docker（推荐）

```bash
docker run --name digital-earth-postgres -d --rm \
  -e POSTGRES_DB=digital_earth \
  -e POSTGRES_USER=app \
  -e POSTGRES_PASSWORD=app_password \
  -p 5432:5432 \
  postgres:15-alpine

docker run --name digital-earth-redis -d --rm \
  -p 6379:6379 \
  redis:7-alpine
```

#### 方式 B：本机安装

请确保 `config/dev.json` 中的 `database.host/port/name`、`redis.host/port` 与本机实际一致。

### 启动后端 API（FastAPI）

1) 安装依赖（需要 Poetry）

```bash
cd apps/api
poetry install
```

2) 设置 `PYTHONPATH`（API 会直接复用仓库内的共享模块与管线代码）

```bash
export REPO_ROOT="$(cd ../.. && pwd)"
export PYTHONPATH="$REPO_ROOT/apps/api/src:$REPO_ROOT/services/data-pipeline/src:$REPO_ROOT/packages/config/src:$REPO_ROOT/packages/shared/src"
```

3) 运行数据库迁移（可选但推荐）

```bash
poetry run alembic -c alembic.ini upgrade head
```

4) 启动 API（开发模式）

```bash
poetry run uvicorn main:app --app-dir src --reload --host 0.0.0.0 --port 8000
```

API 健康检查：

```bash
curl -fsS http://localhost:8000/health
```

### 启动 Web 前端（CesiumJS）

在仓库根目录执行：

```bash
pnpm --filter web dev -- --port 3000
```

### 访问应用

- Web：`http://localhost:3000`
- API：`http://localhost:8000`
- Swagger（直连 API）：`http://localhost:8000/docs`

> 若通过网关统一以 `/api` 前缀对外暴露，Swagger 通常位于 `https://<DOMAIN>/api/docs`（取决于网关/Ingress 是否做了 path rewrite；本仓库 `deploy/nginx/sites-enabled/app.conf` 默认不重写 `/docs`，本地请用直连端口访问）。

## 项目结构

```
Digital-earth/
├── apps/
│   ├── web/                     # Web 前端（CesiumJS + React + Vite）
│   └── api/                     # 后端 API（FastAPI + SQLAlchemy）
├── services/
│   └── data-pipeline/           # 数据处理/切片/体数据导出（xarray/ecCodes）
├── packages/
│   ├── config/                  # 统一配置加载器（Pydantic Settings）
│   └── shared/                  # 共享 Python 逻辑（risk/legend/effect schemas）
├── config/                      # dev/staging/prod 配置 + 业务 YAML/legend
├── docs/                        # 文档（开发规范/UI/运维/用户指南等）
├── deploy/                      # Docker Compose + Nginx + Dockerfiles
├── infra/                       # K8s manifests（Ingress/Secrets/WAF/监控）
├── scripts/                     # 运维/校验脚本（如 WAF smoke test）
└── .env.template                # 环境变量模板（仅示例，不要提交真实 secret）
```

## 开发命令

### 前端（pnpm）

> 根目录脚本定义见 `package.json`；Web 包脚本见 `apps/web/package.json`。

- 安装：`pnpm install`
- 启动 Web：`pnpm --filter web dev -- --port 3000`
- Lint：`pnpm lint`
- Typecheck：`pnpm typecheck`
- 单测：`pnpm test`
- 构建：`pnpm build`
- E2E：`pnpm test:e2e`

### 后端（Poetry）

在 `apps/api/` 目录：

- 安装：`poetry install`
- 启动：`poetry run uvicorn main:app --app-dir src --reload --port 8000`
- 迁移：`poetry run alembic -c alembic.ini upgrade head`
- 测试：`poetry run pytest`

## API 文档

### 在线文档入口

- Swagger UI：
  - 直连：`http://localhost:8000/docs`
  - 网关前缀（示例）：`https://<DOMAIN>/api/docs`
- OpenAPI JSON：
  - 直连：`http://localhost:8000/openapi.json`
  - 仓库快照：`apps/api/openapi.json`

### 关键 Endpoint 概览

> 所有业务 API 统一前缀：`/api/v1`（见 `CLAUDE.md`）。

| 模块 | Endpoint（示例） | 说明 |
|---|---|---|
| 归因/免责声明 | `GET /api/v1/attribution` | 读取 `config/attribution.yaml` 的渲染结果 |
| 图例 | `GET /api/v1/legends/{layer_type}` | 返回图层 legend（默认目录见 `apps/api/src/legend_config.py`） |
| Catalog | `GET /api/v1/catalog/ecmwf/runs` | ECMWF run 列表（Postgres + Redis 缓存） |
| Tiles | `GET /api/v1/tiles/{tile_path}` | 对象存储/本地 tiles（可 302 redirect 或 proxy 返回） |
| CLDAS Tiles | `GET /api/v1/tiles/cldas/{time_key}/{var}/{z}/{x}/{y}.png` | 从本地 CLDAS NetCDF 即时切片 |
| Vector（风场） | `GET /api/v1/vector/ecmwf/{run}/wind/{level}/{time}` | 风矢量采样；支持预热与流线 |
| Products（事件） | `GET /api/v1/products` | 事件产品查询/发布（写接口受 `ENABLE_EDITOR`/token 保护） |
| Risk | `POST /api/v1/risk/evaluate` | 风险评估（规则配置：`config/risk-rules.yaml`） |
| Effects | `GET /api/v1/effects/presets` | 特效预设（默认：`packages/shared/config/effect_presets.yaml`） |
| Volume | `GET /api/v1/volume` | 云体/体数据 VOLP（格式见 `docs/volume-pack.md`） |

## 部署指南

### Docker（单机/Compose）

相关文件：

- Compose：`deploy/docker-compose.base.yml`、`deploy/docker-compose.local.yml`、`deploy/docker-compose.staging.yml`、`deploy/docker-compose.prod.yml`、`deploy/docker-compose.ci.yml`
- Dockerfile：`deploy/dockerfiles/web.Dockerfile`、`deploy/dockerfiles/api.Dockerfile`、`deploy/dockerfiles/pipeline.Dockerfile`
- Nginx：`deploy/nginx/nginx.conf`、`deploy/nginx/sites-enabled/app.conf`

**本地开发（从源码构建 + Compose）**

```bash
# 可选：Cesium ion Web Token（会暴露到浏览器侧，请遵循 docs/cesium-token-security.md）
export DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN="<your-web-token>"

docker compose -f deploy/docker-compose.local.yml up --build
```

> Web 容器会在启动时通过 `deploy/dockerfiles/10-inject-config.sh`（安装到 Nginx 的 `/docker-entrypoint.d/`）将 `apps/web/public/config.template.json` 渲染为运行时 `/config.json`；
> 未设置 `DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN` 时默认注入空字符串，不影响启动。

**本地构建 + Compose（示例）**

```bash
export GITHUB_REPOSITORY=local
export IMAGE_TAG=dev
export DIGITAL_EARTH_DB_PASSWORD=app_password

docker build -f deploy/dockerfiles/web.Dockerfile -t ghcr.io/local/digital-earth-web:dev .
docker build -f deploy/dockerfiles/api.Dockerfile -t ghcr.io/local/digital-earth-api:dev .

docker compose -f deploy/docker-compose.ci.yml up -d
```

> `deploy/nginx/sites-enabled/app.conf` 会对 `/api/v1/tiles/` 启用 Nginx 缓存（默认 1h），并透传/生成 `X-Trace-Id`。

### Kubernetes（基础）

相关目录：`infra/k8s/`

- Namespace：`infra/k8s/namespace-digital-earth.yaml`
- Ingress：
  - Nginx：`infra/k8s/ingress/nginx/*`
  - Traefik：`infra/k8s/ingress/traefik/*`
- TLS（cert-manager）：`infra/k8s/cert-manager/*`
- Secrets 模板与规范：`infra/k8s/secrets/README.md`
- WAF 规则（ModSecurity/OWASP CRS）：`infra/k8s/waf-rules.yaml`（说明见 `docs/waf-configuration.md`）
- 紧急降级开关示例：`infra/k8s/monitoring/emergency-degrade-switch.yaml`

建议结合运维手册执行上线与轮换：

- 运维手册：`docs/ops-manual.md`
- Token 安全：`docs/cesium-token-security.md`、`docs/ue-token-security.md`

## 贡献指南

请先阅读并遵循：

- 项目约束与统一约定：`CLAUDE.md`
- 开发规范：`docs/dev-spec.md`
- UI 设计规范：`docs/ui-design-spec.md`

### 分支命名

```text
feature/<issue-id>-<short-desc>
fix/<issue-id>-<short-desc>
release/v<major>.<minor>.<patch>
```

示例：`feature/ST-0036-catalog-schema`

### Commit 格式

```text
<type>(<scope>): <subject>

type: feat|fix|docs|refactor|test|chore
scope: web|api|data
```

### PR 流程（推荐）

1. 关联 Issue（或在 PR 描述中说明背景与验收口径）
2. 确保本地检查通过：`pnpm lint && pnpm test`（以及 Python `pytest`）
3. 至少 1 人 Review（关键模块建议 2 人）
4. 采用 Squash and Merge

## 许可证

本仓库当前未提供 `LICENSE` 文件，默认视为 **未明确开源许可**（如需对外发布/开源，请先补充许可证与第三方依赖/数据源合规说明）。

数据源许可与归因请以 `config/attribution.yaml` 与页面展示为准。

---

更多文档：

- 技术手册：`docs/technical-manual.md`
- 系统使用手册：`docs/system-manual.md`
- 用户指南：`docs/user-guide.md`
- 运维手册：`docs/ops-manual.md`
