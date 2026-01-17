# Cesium ion Web Token 安全配置指南（Allowed URLs + 最小权限）

> 版本: v1.0 | 更新日期: 2026-01-17

本文档面向运维/发布人员，说明如何为 Digital Earth 的 Web 前端创建与配置 **Cesium ion Web Token**，降低 Token 在浏览器侧暴露后被第三方站点盗用的风险。

## 目标（验收口径）

- **域名白名单**：Token 在非白名单域名（Allowed URLs）发起的请求下不可用。
- **最小权限**：仅授予业务必需的 scopes（优先使用 Public Scopes），并限制可访问的资产（Selected assets）。
- **不入库**：生产环境 Token 不出现在 Git 仓库（含源码与配置 JSON），仅通过环境变量/密钥系统注入。

## 原则与分工（运维联动）

- **开发**提供：Web 端实际使用的 ion 能力清单（是否需要 `geocode`）、以及资产列表（asset IDs / 资产名称）。
- **运维**执行：创建独立 Token、配置 Allowed URLs、配置 scopes 与资产白名单、并负责上线注入与轮换。

## Token 类型建议（务必环境隔离）

| Token 类型 | 典型使用场景 | 是否会出现在浏览器 | 配置要点 |
|---|---:|---:|---|
| Web Token（prod） | 生产 Web 站点加载 ion 资产（地形/3DTiles 等） | 会 | **Allowed URLs=生产域名**；Scopes 最小化；Selected assets；可公开但需受限 |
| Web Token（staging/dev） | 预发/开发环境验证 | 会 | Allowed URLs=对应环境域名（可选）；Scopes 最小化；与 prod 分离 |
| Private Token（CI/后端） | 上传/管理资产、自动化 | 不会 | 仅在服务端/CI 使用；绝不下发给浏览器；可用 Private Scopes，但必须最小化 |

## 1) 创建独立 Web Token（Cesium ion 控制台）

1. 登录 Cesium ion 控制台，进入 **Access Tokens** 页面。
2. 点击 **Create new token**，为当前应用创建一个独立 Token（不要复用 Default Token）。
3. 设置 Token 名称（建议包含环境与用途），例如：
   - `digital-earth-web-prod`
   - `digital-earth-web-staging`
4. 按下文分别配置：
   - Scopes（最小化）
   - Asset Restrictions（资产白名单）
   - URL Restrictions / Allowed URLs（域名白名单）

> 参考：Cesium ion 官方文档（Access Tokens / Scopes / Allowed URLs / Asset Restrictions）  
> https://cesium.com/learn/ion/cesium-ion-access-tokens/

## 2) Scopes 最小化（推荐配置）

Cesium ion scopes 分为 **Public Scopes**（适合公开客户端）与 **Private Scopes**（敏感/可修改账号资源，必须保密）。

### 2.1 Web Token（浏览器侧）推荐

- 必选：`assets:read`（读取资产元数据并访问资产瓦片数据）
- 可选：`geocode`（仅当 Web 端使用 ion geocode 服务时开启，例如 CesiumJS 默认 Search/Geocoder）

**Web Token 严禁开启（Private Scopes）**：

- `assets:list`（可枚举账号下全部资产）
- `assets:write`（可创建/修改/删除资产）
- `profile:read`（读取账号信息与配额）
- `tokens:read` / `tokens:write`（可读取/管理 Token）

### 2.2 Private Token（仅服务端/CI）推荐思路

按任务最小化勾选，例如“自动化上传资产”通常只需要：

- `assets:read` + `assets:write`（必要时再加 `assets:list` 以便定位资产）

## 3) 资产最小化（Asset Restrictions / Selected assets）

默认情况下，只要 Token 有 `assets:read`，就可以访问账号下 **全部资产**。为降低被盗用后的横向风险，建议启用资产白名单：

1. 在 Token 配置中找到 **Asset Restrictions**。
2. 选择 **Selected assets**，仅勾选 Web 端实际需要的资产（例如：Cesium World Terrain、OSM Buildings、项目自有 tileset 等）。
3. 后续资产变更（新增/替换 tileset）时，同步更新 Token 的 Selected assets 列表。

## 4) Allowed URLs（生产域名白名单）

### 4.1 配置要点

- Allowed URLs 必须包含 **协议**（http/https）与 **域名**，可选包含子域名、端口、路径。
- **匹配规则**（重要）：
  - 仅配置 `https://example.com` 会允许该域名下的任意子域与子路径。
  - `https://example.com` **不会**允许 `http://example.com`（协议不同即不匹配）。
  - 如配置到路径粒度（例如 `https://example.com/app/`），可能会受到浏览器 `Referrer-Policy` 影响导致不稳定，生产建议优先仅限制到 **域名粒度**。
- 配置 Allowed URLs 的 Token 请求必须带 `Referer` 头；如站点设置了 `Referrer-Policy: no-referrer` 可能导致 Token 在白名单域名也不可用。

### 4.2 生产域名示例

假设生产站点域名为 `https://digital-earth.example`（按实际替换），建议在 **URL Restrictions** 中选择 **Selected URLs** 并添加：

- `https://digital-earth.example`
- 如存在独立子域（例如 `https://app.digital-earth.example` 或 `https://www.digital-earth.example`），按实际逐条添加

## 5) 项目侧注入方式（生产 Token 不入库）

仓库统一使用 `DIGITAL_EARTH_*` 前缀管理环境变量；Cesium ion Web Token 的规范命名如下：

- `DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN`（推荐/当前规范）
- `DIGITAL_EARTH_CESIUM_ION_ACCESS_TOKEN`（历史兼容别名，不推荐新增使用）

### 5.1 环境变量配置示例

本地/预发可在 `.env`（已被 `.gitignore` 忽略）中配置；生产环境通过 Secret 注入（K8s Secret、CI/CD Secret、参数存储等）：

```bash
# Cesium ion Web Token（会暴露在浏览器中，因此必须配置 Allowed URLs + 最小 scopes + Selected assets）
DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN="<your-web-token>"
```

> 注意：`DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN` 不允许设置为空字符串；未配置时建议直接不设置该变量。

### 5.2 上线检查清单（运维）

- Token 名称包含环境标识（prod/staging/dev），且 **prod 与 staging/dev Token 不复用**。
- prod Web Token：只启用 `assets:read`（如需要再加 `geocode`），并启用 Selected assets。
- prod Web Token：Allowed URLs 仅包含生产站点域名（https），无多余域名/端口。
- 确认发布产物与仓库中不包含真实 Token（包括 `config/*.json`、`apps/web/public/config*.json`、源码等）。
- 具备 Token 轮换预案（泄露时 Regenerate/禁用旧 Token，并同步更新 Secret）。

## 6) 验证方法（白名单生效）

可用 `curl` 模拟不同 `Referer` 下的 ion API 请求，验证 Allowed URLs 是否生效（将 `<TOKEN>` 与 `<ASSET_ID>` 替换为实际值；`<ASSET_ID>` 需在 Selected assets 中被允许）：

```bash
# 允许的 Referer（期望 200）
curl -sS -o /dev/null -w "%{http_code}\n" \\
  -H "Referer: https://digital-earth.example/" \\
  "https://api.cesium.com/v1/assets/<ASSET_ID>/endpoint?access_token=<TOKEN>"

# 非白名单 Referer（期望 4xx）
curl -sS -o /dev/null -w "%{http_code}\n" \\
  -H "Referer: https://evil.example/" \\
  "https://api.cesium.com/v1/assets/<ASSET_ID>/endpoint?access_token=<TOKEN>"
```

