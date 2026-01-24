# 系统使用手册（Digital Earth）

> 面向：终端用户（业务/分析）与运维人员（发布/值班）  
> 目标：说明平台功能、Web 端操作、数据口径与运维操作手册（可执行命令）。

---

## 1. 系统概述

Digital Earth（数字地球气象可视化平台）提供基于 3D 地球的气象数据展示与分析能力，支持：

- **全球气象概览（Global）**：快速浏览全球范围温度/云量/降水/风场等要素
- **点位局地仰视（Local）**：在指定点位查看局地信息与天空/云层效果
- **区域事件（Event）**：围绕事件/产品（如降雪、风险区域）进行聚焦分析
- **锁层全球（LayerGlobal）**：专注查看某一图层在全球的分布与渲染效果

平台强调“数据来源归因与免责声明”：

- 归因配置：`config/attribution.yaml`
- Web 端底部归因栏可查看来源、许可与免责声明（API：`GET /api/v1/attribution`）

---

## 2. Web 端使用

> 详细版可参考：`docs/user-guide.md`。本文提供“上手版 + 运维关注点”。

### 2.1 界面布局说明

```
┌─────────────────────────────────────────────────────────────┐
│  [Logo]  场景切换                               [设置] [帮助] │  ← 顶部导航栏
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐           Cesium 地球视图         ┌─────────┐ │
│  │ 图层面板 │           (全屏背景)              │ 信息面板│ │
│  │ (左侧)   │                                   │ (右侧)  │ │
│  └──────────┘                                   └─────────┘ │
│                                                             │
│                                          [归因与数据来源]   │
├─────────────────────────────────────────────────────────────┤
│  ◀ ▶ ⏸  |  2026-01-15 12:00 UTC  |  ═══════●═══════        │  ← 底部时间轴
└─────────────────────────────────────────────────────────────┘
```

- **左侧图层面板**：图层开关、透明度、图层切换（同类型互斥显示）
- **右侧信息面板**：点位/事件详情、设置（性能模式/体素云画质等）
- **底部时间轴**：时间选择、播放/暂停、帧切换
- **归因栏**：数据来源、免责声明（必须展示，见 `CLAUDE.md` 的约束）

### 2.2 四种视图模式详解

视图模式命名与状态机约定见：`apps/web/src/state/viewMode.ts`

#### A) Global（全球视图）

适用场景：全球概览、快速切换气象要素。

基本操作：

- 旋转：鼠标左键拖拽
- 缩放：滚轮
- 平移：鼠标右键拖拽（或 Ctrl + 左键拖拽）

#### B) Local（点位仰视）

适用场景：查看某个地理点位的局地信息（如云层/风场/风险提示）。

进入方式（默认交互，可能随版本调整）：

- 地球上 **双击** 或 **Ctrl + 单击** 某位置进入

退出方式：

- 点击面板「返回」或按 `ESC`

#### C) Event（区域事件）

适用场景：围绕事件产品（例如降雪事件/风险区域）进行聚焦查看。

进入方式：

- 在右侧信息面板的事件/产品列表中选择某事件

#### D) LayerGlobal（锁层全球）

适用场景：专注某一层的全球渲染（例如 500hPa 风场、云量层等）。

进入方式：

- 在图层列表中点击图层名称进入锁层模式（以 UI 行为为准）

### 2.3 图层控制

平台内置的图层类型以当前前端实现为准（见 `apps/web/src/state/layerManager.ts`）：

- `temperature`（温度）
- `cloud`（云量/云层）
- `precipitation`（降水）
- `wind`（风场）
- `snow-depth`（积雪深度）

常见规则：

- **同类型互斥**：同一类型图层一次仅显示一个（避免叠加造成误读与性能压力）
- **透明度可调**：用于对比底图与多源数据

### 2.4 时间轴操作

- 时间轴时间为 **UTC**
- 支持播放/暂停、逐帧前进/后退、拖动跳转

若出现“数据缺失/已降级展示”，通常原因：

- 当前时间点数据尚未生成或缺测
- 网络请求失败或 API 限流（429）
- 低性能模式触发降级（见下一节）

### 2.5 性能模式设置

设置入口：右侧信息面板 → 设置（以 UI 为准）

- **High**：更完整的渲染效果（更高消耗）
- **Low**：降级渲染以保证帧率（会关闭部分预取、降低体素云质量等）

体素云（Voxel Cloud）相关：

- 质量档位：High / Medium / Low（状态管理：`apps/web/src/state/performanceMode.ts`）
- 自动降级：当帧率持续低于阈值时，自动调整步进/最大步数/质量（实现见 `apps/web/src/features/voxelCloud/*`）

---

## 3. 数据说明

### 3.1 支持的气象要素

以当前实现与配置为准（图层/接口会持续扩展）：

- 温度（temperature）
- 云量/云密度（cloud / cloud_density）
- 降水（precipitation）
- 风场（wind：矢量/流线）
- 积雪/积雪深度（snow / snow-depth）
- 风险评估/风险点（risk）

### 3.2 数据更新频率（基线）

基线口径（见 `CLAUDE.md`）：

- ECMWF：约 **6 小时**更新（预报数据）
- CLDAS：约 **1 小时**更新（区域精细化数据）

> 实际可用性取决于数据落库/切片任务是否完成与是否缺测。

### 3.3 数据来源归因

数据来源、许可与免责声明统一由 `config/attribution.yaml` 管理，并在 Web 端展示：

- API：`GET /api/v1/attribution`
- 运营/合规要求：不得删除或隐藏归因与免责声明展示区域

---

## 4. 运维操作

> 详细 Runbook 请参考：`docs/ops-manual.md`。本文是“常用操作速查”。

### 4.1 日志查看

#### Docker Compose

```bash
# 查看网关（nginx）
docker compose -f deploy/docker-compose.prod.yml logs -f nginx

# 查看 API
docker compose -f deploy/docker-compose.prod.yml logs -f api

# 查看 Web
docker compose -f deploy/docker-compose.prod.yml logs -f web
```

#### Kubernetes

```bash
kubectl -n digital-earth get pods
kubectl -n digital-earth logs deploy/digital-earth-api --tail=200
kubectl -n digital-earth logs deploy/digital-earth-web --tail=200
```

### 4.2 监控告警（建议最小集合）

建议在监控系统中至少覆盖（口径详见 `docs/ops-manual.md`）：

- API：5xx 错误率、p95/p99 延迟、429 比例、503（限流器不可用）
- Nginx/Ingress：upstream 5xx、超时、缓存命中率
- Redis/Postgres：连接数/内存/慢查询
- Cesium ion：token 用量/费用异常（P0）

### 4.3 常见问题排查

#### 问题 A：页面白屏 / 地球不显示

- 检查浏览器控制台是否出现资源加载失败（网络/CORS）
- 若使用 Cesium ion 资源：确认 token 与 Allowed URLs 配置（见 `docs/cesium-token-security.md`）
- 检查 Web 配置：`apps/web/public/config.json` 中 `apiBaseUrl` 是否指向可用 API

#### 问题 B：图层加载失败 / 数据缺失

- API 健康检查：

```bash
curl -fsS http://<API_HOST>:8000/health
```

- 检查是否被限流（HTTP 429）：
  - 适当调高阈值或在边缘做更精细的限流/封禁（见 `docs/ops-manual.md`）
- 检查本地数据索引（CLDAS 本地模式）：
  - `GET /api/v1/local-data/index`
  - 数据目录默认在 `Data/`（可由 `config/local-data.yaml` 覆盖）

#### 问题 C：大量 403（WAF 拦截）

- 检查 WAF 规则与日志：
  - 文档：`docs/waf-configuration.md`
  - 规则：`infra/k8s/waf-rules.yaml`
- 使用脚本自检（示例）：

```bash
./scripts/waf-smoke-test.sh https://<DOMAIN>
```

### 4.4 Token 轮换（Cesium ion）

轮换原则：**先上新 token → 验证 → 再吊销旧 token**，避免中断。

K8s 命令示例（仅示例，替换为真实 secret 名称与 token）：

```bash
kubectl -n digital-earth create secret generic web-cesium-ion-token \
  --from-literal=DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN='<NEW_TOKEN>' \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n digital-earth rollout restart deployment/digital-earth-web
kubectl -n digital-earth rollout status deployment/digital-earth-web
```

详细流程与应急方案见：`docs/ops-manual.md`（含盗刷应急）。

---

## 5. 附录

### 5.1 快捷键参考（Web）

（以当前实现为准）

| 按键/操作 | 功能 |
|---|---|
| 鼠标左键拖拽 | 旋转视角 |
| 鼠标右键拖拽 | 平移 |
| 鼠标滚轮 | 缩放 |
| 双击 / Ctrl+单击 | 进入 Local 模式（点位仰视） |
| `ESC` | 关闭弹窗/返回上一视图 |

### 5.2 API 响应码（通用口径）

API 约定见 `CLAUDE.md`（`X-Trace-Id` 贯穿）：

- **200**：成功
- **302**：Tiles redirect 到对象存储（当 `redirect=true` 且可构造 URL）
- **304**：缓存命中（ETag）
- **400**：参数错误/数据不可解析
- **403**：禁止访问（WAF/黑名单/编辑接口无权限）
- **404**：资源不存在（数据缺失、时间/层级不存在）
- **429**：触发限流（RateLimitMiddleware）
- **503**：依赖不可用（Postgres/Redis 不可用、Volume 目录未配置等）

### 5.3 联系支持

- 应用内：右上角「帮助」（如已接入）
- 项目 Issues：`https://github.com/DankerMu/Digital-earth/issues`
- 运维值班：请按团队内部值班机制与通讯录（本仓库不存放私密联系方式）

