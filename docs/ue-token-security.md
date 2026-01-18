# UE（Cesium for Unreal）Token 安全配置指南（独立 Token + 最小权限）

> 版本: v1.0 | 更新日期: 2026-01-18

本文档面向运维/发布人员，说明如何为 **Unreal Engine（Cesium for Unreal）客户端**创建与注入 Cesium ion Token，目标是在“客户端可被提取”的前提下尽可能降低泄露后的可用范围与横向风险。

## 1) 为什么 UE 需要独立 Token

UE 打包产物属于 **分发到终端用户的客户端环境**（可被反编译、抓包、内存提取），与 Web 前端的安全模型不同：

- **无法依赖 Allowed URLs / Referer 白名单**：这类限制主要针对浏览器侧请求，UE 原生客户端通常不具备可用/可信的 Referer 约束机制。
- **泄露影响面更大**：一旦 Token 被提取，攻击者可在任意环境复用该 Token 访问 ion 资产。
- **避免跨端连坐**：严禁复用 Web Token（`DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN`）。UE Token 泄露不应影响 Web 端；Web Token 的 Allowed URLs / 资产白名单策略也不应被 UE 的需求“放大”。

结论：UE 必须使用 **独立 Token**，并严格执行 **最小 scopes + Selected assets**。

## 2) 最小权限 scopes（仅 `assets:read`）

UE 侧仅需要加载资产瓦片（地形/影像/3DTiles），通常只需要：

- 必选：`assets:read`

严禁为 UE Token 开启以下高风险 scopes（不完整列表，见 `config/ue-token-scopes.yaml`）：

- `assets:list` / `assets:write`
- `profile:read`
- `tokens:read` / `tokens:write`

> 规范定义：`config/ue-token-scopes.yaml`

## 3) 资产白名单（Selected assets）

即使只授予 `assets:read`，默认仍可能访问账号下的全部资产。为降低泄露后的横向风险，必须在 Cesium ion 控制台对 UE Token 启用：

- **Asset Restrictions → Selected assets**

并将资产范围限制为 UE 实际需要的三类资产（按项目实际选择）：

- Terrain（地形）
- Imagery（影像）
- 3D Tiles / Tilesets（瓦片/模型）

## 4) Token 注入（UE 打包/发布流程）

原则：真实 Token **不入库**，仅在打包/发布时通过 Secret 注入。

### 4.1 环境变量命名

UE 专用 Token 使用：

- `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN`

### 4.2 CI/打包注入（推荐）

- GitHub Actions：将 Token 存入仓库/组织 Secret（例如 `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN`），在 UE 打包 Job 中以环境变量注入。
- 若需要写入 UE 配置文件（例如 Cesium for Unreal 的 Project Settings 对应的 `Config/*.ini`），在 **BuildCookRun 之前**执行一次“占位符替换”（把 `<REPLACE_ME>` 写入到最终用于打包的配置里），并确保生成的真实配置文件不被提交。

> 注意：不同 Cesium for Unreal 版本/项目结构的配置项可能不同；以项目实际 `Config/*.ini` 与插件文档为准。

### 4.3 Kubernetes Secret（可选）

如使用 K8s 统一管理发布/构建环境，可参考模板：

- `infra/k8s/secrets/ue-cesium-ion-token.secret.template.yaml`

并在工作负载中将 `DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN` 注入为环境变量。

## 5) 吊销与轮换（Revocation/Rotation）

轮换目标：最小化中断，并保证可回滚。

### 5.1 标准轮换流程（推荐）

1. 在 Cesium ion 控制台创建 **新 UE Token**（独立命名，按环境区分 `prod/staging/dev`）。
2. 只授予 `assets:read`，并设置 **Selected assets**（地形/影像/tileset）。
3. 更新密钥注入位置：
   - GitHub Actions Secret（用于夜间/发布打包），或
   - K8s Secret（用于集群内构建/运行）
4. 触发一次 UE 打包/发布，验证客户端可正常加载相关资产。
5. 观察窗口后（建议 ≥24h，覆盖缓存/旧版本分发窗口），在 ion 控制台 **吊销旧 Token**。

### 5.2 泄露应急（10 分钟止血）

1. 立即生成新 Token（同 5.1 的最小化要求）。
2. 立刻更新 CI/K8s Secret 并重新打包（或发布热更新）。
3. 在确认新版本可用后，吊销旧 Token；必要时可先吊销旧 Token 以快速止血（可能影响旧版本客户端）。

