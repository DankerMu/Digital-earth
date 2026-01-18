# UE Token 安全配置指南（独立 Token + 最小权限 Scopes）

> 版本: v1.0 | 更新日期: 2026-01-18

本文档面向运维/发布人员与 UE 开发，说明如何为 **UE5 客户端（Cesium for Unreal）** 配置独立 Token，并通过 **最小权限 scopes + 资产白名单** 降低 Token 泄露后的风险。

> 背景：UE 客户端会将 Token 打包进发布产物，严格意义上属于“可被提取”的客户端凭据，因此必须按 **Public Token** 的安全标准治理（可吊销、最小权限、最小资产范围）。

## 目标（验收口径）

- **独立 Token**：UE 与 Web/CI/后端使用的 Token 必须隔离，且 prod/staging/dev 分离。
- **最小权限**：UE Token 仅具备读取所需资产的能力（tiles/terrain/imagery），不具备任何管理/写入权限。
- **资产最小化**：启用 Cesium ion 的 **Selected assets** 白名单，仅允许 UE 实际使用的资产。
- **不入库**：真实 Token 不出现在 Git 仓库、CI 日志与发布说明中，仅通过 Secret 注入。
- **可吊销/可轮换**：Token 可随时禁用/吊销；轮换流程可执行且可回滚。

## 原则与分工（运维联动）

- **UE 开发提供**：UE 项目实际用到的 ion 资产清单（Terrain/Imagery/Tileset 的 asset IDs 或名称）。
- **运维执行**：创建独立 Token、配置 scopes 与 Selected assets，并负责 CI/发布注入与轮换。

## 1) 创建独立 UE Token（Cesium ion 控制台）

1. 登录 Cesium ion 控制台，进入 **Access Tokens**。
2. 点击 **Create new token**，为 UE 客户端创建独立 Token（不要复用 Default Token，也不要复用 Web Token）。
3. Token 命名建议包含环境与用途，例如：
   - `digital-earth-ue-prod`
   - `digital-earth-ue-staging`
   - `digital-earth-ue-dev`

## 2) Scopes 最小化（推荐配置）

UE 客户端只需要读取 tiles/terrain/imagery，因此 **只启用**：

- `assets:read`（读取资产元数据并访问资产瓦片/地形/影像数据）

**UE Token 严禁开启（示例，属敏感/管理权限）**：

- `assets:list`（可枚举账号下全部资产）
- `assets:write`（可创建/修改/删除资产）
- `profile:read`（读取账号信息与配额）
- `tokens:read` / `tokens:write`（可读取/管理 Token）

## 3) 资产最小化（Selected assets）

默认情况下，只要 Token 有 `assets:read`，就可能访问账号下 **全部资产**。UE Token 必须启用资产白名单：

1. 在 Token 配置中找到 **Asset Restrictions**。
2. 选择 **Selected assets**。
3. 仅勾选 UE 客户端实际需要的资产（至少三类）：
   - Tiles（3D Tiles / Tileset）
   - Terrain（地形，例如 Cesium World Terrain 或自有地形）
   - Imagery（影像底图/叠加图层）
4. 后续资产变更（新增/替换 tileset/影像/地形）时，同步更新 Selected assets 列表。

## 4) URL Restrictions（UE 的特殊说明）

与 Web 不同，UE 客户端请求通常不携带浏览器 `Referer`。如果为 UE Token 配置 **Allowed URLs**（Selected URLs），可能导致 UE 请求因缺少/不匹配 Referer 被拒绝。

建议：

- UE Token：**不启用 URL Restrictions（No restrictions）**
- 安全依赖：**最小 scopes + Selected assets + 独立 Token + 轮换/吊销**

## 5) 项目侧注入方式（UE 打包/发布）

仓库统一使用 `DIGITAL_EARTH_*` 前缀管理环境变量；UE Token 的规范命名如下：

- `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN`

### 5.1 GitHub Actions（Nightly 打包）注入

仓库已在 `.github/workflows/nightly.yml` 中提供注入步骤：从 GitHub Actions Secret 读取 Token，并写入 UE 工程配置文件。

配置步骤：

1. 在 GitHub 仓库 Secrets 中新增：
   - `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN` = `<your-ue-token>`
2. Nightly 任务会在打包前写入（或更新）：
   - `apps/ue-client/Config/DefaultEngine.ini`

写入的配置片段（示例）：

```ini
[/Script/CesiumRuntime.CesiumRuntimeSettings]
DefaultIonAccessToken=<TOKEN>
```

> 注意：该 Token 会进入打包产物，需按“公开客户端 token”治理（最小权限+资产白名单+可吊销）。

### 5.2 Kubernetes Secret（可选：用于构建集群/发布系统）

如 UE 构建/发布在 K8s 内执行，可使用本仓库模板（仅模板，禁止提交真实值）：

- `infra/k8s/secrets/ue-cesium-ion-token.secret.template.yaml`

## 6) 轮换与吊销（建议流程）

1. 创建新 UE Token（保持最小 scopes + Selected assets）。
2. 更新 Secret（GitHub Actions Secret 或 K8s Secret）。
3. 重新打包并发布新版本客户端。
4. 观察窗口（建议 ≥24h，覆盖旧版本自然淘汰周期）。
5. 在 ion 控制台吊销旧 Token。

## 7) 上线检查清单

- Token 名称包含环境标识，且 UE/Web/CI Token **不复用**。
- UE Token scopes 仅 `assets:read`；未启用任何管理/写入权限。
- UE Token 已启用 Selected assets，且资产清单覆盖 tiles/terrain/imagery 的实际使用范围。
- 真实 Token 未进入仓库与发布物料（日志/README/截图/工单等）。
- 具备轮换预案：Secret 可更新，旧 Token 可随时吊销止血。
