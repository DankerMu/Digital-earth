# 运维手册：Token 轮换、限流、缓存、告警（Issue #184 / ST-0153）

> 版本: v1.0 | 更新日期: 2026-01-17  
> 适用范围：Digital Earth（Web + API + Nginx + Redis + PostgreSQL + CDN + K8s）

本文档面向运维/值班同学，提供**上线**与**故障处理**的可执行手册，覆盖：

- Cesium token 轮换（含盗刷应急）
- CDN/边缘缓存规则与刷新策略（含缓存穿透/回源风暴处理）
- API 限流阈值调整（含流量突增演练）
- 告警处理与降级开关（含应急响应流程）

> 约束：遵循 `docs/dev-spec.md`（环境变量前缀、配置与 secrets 分离、HTTP 约定等）。

---

## 0) 快速索引（文件与关键配置）

- 环境变量模板：`.env.template`
  - Cesium token：`DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN`（**secret**，禁止写入 `config/*.json`）
- 运行配置（非 secret）：`config/dev.json`、`config/staging.json`、`config/prod.json`
  - API 限流：`config/<env>.json` → `api.rate_limit`
- Docker Compose（含 Nginx 反向代理与缓存）：`deploy/docker-compose.*.yml`、`deploy/nginx/sites-enabled/app.conf`
- K8s Ingress 模板：`infra/k8s/ingress/**`（namespace：`digital-earth`）
- TLS/域名：`docs/infra/tls-cert-manager.md`

---

## 1) 上线手册（通用）

### 1.1 上线前检查清单（5 分钟）

- [ ] 确认环境：`DIGITAL_EARTH_ENV=staging|prod`
- [ ] 配置文件存在且不含 secrets：`config/<env>.json`
  - 禁止在 JSON 中出现：`web.cesium_ion_access_token`、`database.password` 等（由配置加载器强校验）
- [ ] secrets 已注入（至少 DB/Redis/Cesium/对象存储）
- [ ] 依赖服务可用：Redis、PostgreSQL
- [ ] 入口连通：Ingress/反向代理/证书正常

### 1.2 上线后验收（冒烟）

> 如果通过 Ingress 仅暴露 `/api/v1`，建议用 `port-forward` 直接探测 API `/health`。

```bash
# K8s：检查 Ingress/Pod 状态
kubectl -n digital-earth get ingress,svc,pods

# API 健康检查（示例：端口转发后）
kubectl -n digital-earth port-forward svc/digital-earth-api 8000:8000
curl -fsS http://localhost:8000/health

# 检查缓存/ETag（示例：效果预设，应该支持 304）
curl -i https://<DOMAIN>/api/v1/effects/presets
curl -i -H 'If-None-Match: "<ETAG_FROM_PREV>"' https://<DOMAIN>/api/v1/effects/presets
```

---

## 2) Cesium token 轮换步骤（含盗刷应急）

### 2.1 背景与原则

- Cesium token 属于 **secret**：必须通过环境变量/Secret 下发，不得进入 `config/*.json` 或仓库。
- 轮换目标：
  - **最小化中断**：先发新 token、验证通过后再吊销旧 token
  - **可回滚**：保留旧 token 一段时间（直到确认无旧版本缓存/长连接）

### 2.2 标准轮换流程（推荐）

1) **生成新 token（Cesium Ion 控制台）**

- 创建新 token，权限遵循最小化原则（只给需要的 Asset/服务权限）
- 记录：token ID、创建人、时间、预计吊销时间（建议 ≥24h）

2) **更新运行环境 secret**

#### 方案 A：Kubernetes（推荐）

> 以下命令以 `digital-earth` namespace 为例；`<SECRET_NAME>` / `<DEPLOYMENT>` 以实际资源为准。  
> 注意：避免在命令行/日志中回显 token；必要时使用安全的 Secret 管理与审计策略。

```bash
# 将 token 写入 K8s Secret（示例：以 env var 形式提供）
kubectl -n digital-earth create secret generic <SECRET_NAME> \
  --from-literal=DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN='<NEW_TOKEN>' \
  --dry-run=client -o yaml | kubectl apply -f -

# 触发滚动更新（确保新 Pod 读取新 secret）
kubectl -n digital-earth rollout restart deployment/<DEPLOYMENT>
kubectl -n digital-earth rollout status deployment/<DEPLOYMENT>
```

#### 方案 B：Docker Compose

```bash
# 1) 写入部署机的环境变量（或 .env 文件）
export DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN='<NEW_TOKEN>'

# 2) 重启相关服务（以 prod compose 为例）
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps --force-recreate web
```

3) **验证**

- Web 端（浏览器）：
  - Cesium 资源加载正常（不出现 token unauthorized）
  - 控制台无持续的 401/403（与 Cesium Ion 相关）
- 可选：直接用 Cesium Ion API 验证 token（以官方接口为准）

```bash
curl -fsS -H "Authorization: Bearer <NEW_TOKEN>" https://api.cesium.com/v1/me
```

#### 回滚预案（必备）

- 如果上线新 token 后出现大面积不可用（例如 Cesium 资源无法加载），优先回滚到旧 token 以恢复服务：
  - K8s：将 Secret 中的 `DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN` 改回旧值 → `rollout restart`
  - Docker Compose：将 env 改回旧值 → 重建 web
- 回滚后再排查：token 权限范围、是否误复制（前后空格/换行）、CDN/浏览器缓存导致的“混用旧版本 JS”

4) **观察窗口**

- 建议观察 ≥30 分钟：
  - Cesium Ion 用量曲线回落/平稳
  - 客户端错误率未上升

5) **吊销旧 token**

- 在确认新 token 生效、且旧版本前端缓存自然淘汰后，再在 Cesium Ion 控制台吊销旧 token

### 2.3 盗刷应急流程（演练/实战）

**触发信号（任一满足即可升级处理）：**

- Cesium Ion 用量/费用异常陡增（分钟级）
- Web 端出现大量与 token 相关的 401/403（可能是被吊销后旧版本仍在请求）
- 外网出现异常来源访问 Cesium 资源（可从 Ion/监控侧观测）

**应急步骤（目标：10 分钟内止血）：**

1) **升级事件等级**（参见第 6 章应急响应流程），指定负责人（IC）
2) **立即生成新 token**（复用 2.2 的 Step 1）
3) **快速上线新 token**
   - K8s：更新 Secret → `rollout restart`
   - Docker Compose：更新 env → 重建 web
4) **短期止血措施（可选，根据风险选择）**
   - 若盗刷持续且无法立刻定位来源：先吊销旧 token（会导致旧版本客户端短时受影响）
   - CDN/WAF：对可疑国家/ASN/IP 段临时拦截（以实际 CDN 能力为准）
5) **验证与观察**
   - 用量曲线回落
   - 前端恢复正常
6) **根因与复盘**
   - 排查泄露来源：仓库、CI 日志、前端打包产物、截图/文档、监控面板共享等
   - 建议将 token 存放在 Secret 管理系统（K8s Secret/外部 KMS），限制可见范围

---

## 3) CDN 缓存规则与刷新策略（含回源风暴处理）

### 3.1 缓存对象分类（建议按路径配置）

| 对象 | 路径示例 | 建议策略 | 说明 |
|---|---|---|---|
| 静态资源 | `/*.js` `/*.css` `/*.png` | `Cache-Control: public, immutable`，TTL 1y | 依赖文件名 hash/版本化，避免频繁 purge |
| 运行时配置 | `/config.json` | `Cache-Control: no-store`，TTL 0 | 配置变更需要秒级生效 |
| API 可缓存元数据 | `/api/v1/attribution`、`/api/v1/effects/presets`、`/api/v1/risk/intensity-mapping` | 依赖 `ETag`，`must-revalidate` | 后端已实现 304（可减少带宽） |
| tiles（二进制） | `/api/v1/tiles/**` | Edge + Origin 分层缓存，TTL 1h～24h | 以数据时效要求决定 TTL |

### 3.2 Origin 侧缓存（Docker Compose Nginx）

仓库已提供 Nginx 配置示例：`deploy/nginx/sites-enabled/app.conf`

- tiles 缓存：
  - `proxy_cache tiles_cache;`
  - `proxy_cache_valid 200 1h;`
  - `proxy_cache_key $uri$is_args$args;`（缓存 key 包含 query string）
  - 返回 `X-Cache-Status: HIT|MISS|BYPASS` 便于排障

**修改缓存 TTL（示例：将 tiles 从 1h 调到 6h）**

```bash
rg -n "proxy_cache_valid" deploy/nginx/sites-enabled/app.conf
# 编辑后重载 Nginx（容器内）
docker compose -f deploy/docker-compose.prod.yml exec nginx nginx -s reload
```

**紧急清空 origin cache（示例）**

```bash
# 仅清理 tiles 缓存目录（路径来自 deploy/nginx/nginx.conf）
docker compose -f deploy/docker-compose.prod.yml exec nginx sh -lc 'rm -rf /var/cache/nginx/tiles/*'
docker compose -f deploy/docker-compose.prod.yml exec nginx nginx -s reload
```

### 3.3 CDN 侧规则（建议）

> CDN 规则因厂商不同而差异较大，原则上：**尊重源站 Cache-Control**，对特殊路径做覆盖。

推荐最小规则集：

1) `/config.json`：强制不缓存（TTL=0，绕过缓存）
2) `*.js|*.css|*.png|*.jpg|*.svg|*.woff2`：长缓存（TTL=30d～365d），并启用 `immutable`
3) `/api/v1/*`：
   - 默认不做强制缓存覆盖（尊重源站）
   - 对 `/api/v1/tiles/*` 可设置 Edge TTL（例如 1h）并开启 **stale-if-error**

### 3.4 刷新（purge）策略

**优先级：避免 purge > 小范围 purge > 全站 purge（最后手段）**

- 静态资源：使用文件名版本化（hash），尽量不 purge
- `/config.json`：不缓存，通常无需 purge
- tiles：建议设计“版本参数/版本路径”（例如 `.../tiles/<dataset_version>/...` 或 query `v=`），实现发布即失效

### 3.5 缓存相关故障排查（流程）

**症状 A：用户看到旧数据/旧配置**

1) 确认源站响应头（本地直连源站/回源探测）：
```bash
curl -i https://<DOMAIN>/config.json
curl -i https://<DOMAIN>/api/v1/effects/presets
```
2) 观察 CDN 返回头（`Age`、`X-Cache` 等，因厂商而异）
3) 若确定是 CDN 命中旧缓存：
   - 优先对单个路径 purge：`/config.json` 或具体 tiles 前缀
   - 同步检查 origin Nginx 缓存（如启用）

**症状 B：回源风暴/带宽打满**

- 立即措施（按影响从小到大）：
  1) CDN 开启 `stale-if-error` / `serve stale`（避免源站抖动放大）
  2) 临时提升 tiles TTL（降低回源）
  3) 对异常来源限流/封禁（CDN/WAF 或 API 侧 blocklist）

---

## 4) 限流阈值调整（API）

### 4.1 当前实现（仓库内）

- 中间件：`apps/api/src/rate_limit.py`
- 存储：Redis（滑动窗口，ZSET + Lua 脚本）
- 行为：
  - 命中限流：HTTP `429`，包含 `Retry-After`
  - Redis 不可用：HTTP `503`（Rate limiter unavailable）
- 默认规则（如未配置）：来自 `packages/config/src/digital_earth_config/settings.py`

### 4.2 配置方式（推荐：改 `config/<env>.json`）

在 `config/prod.json`（或 staging）中加入 `api.rate_limit`，示例：

```json
{
  "api": {
    "rate_limit": {
      "enabled": true,
      "trust_proxy_headers": true,
      "ip_allowlist": ["10.0.0.0/8", "192.168.0.0/16"],
      "ip_blocklist": [],
      "rules": [
        {"path_prefix": "/api/v1/tiles", "requests_per_minute": 600, "window_seconds": 60},
        {"path_prefix": "/api/v1/effects", "requests_per_minute": 120, "window_seconds": 60}
      ]
    }
  }
}
```

> 提醒：`requests_per_minute` / `window_seconds` 必须为正数；`path_prefix` 会自动规范化（补 `/`、去尾 `/`）。

### 4.3 生效步骤

#### 方案 A：Docker Compose

`deploy/docker-compose.base.yml` 将 `../config:/config:ro` 挂载进 API 容器，配置在进程启动时加载。

```bash
# 1) 修改 config/prod.json（部署机上的文件）
# 2) 重启 API
docker compose -f deploy/docker-compose.prod.yml up -d --no-deps --force-recreate api

# 3) 验证：制造超限请求，预期返回 429
for i in $(seq 1 20); do curl -s -o /dev/null -w "%{http_code}\n" https://<DOMAIN>/api/v1/effects/presets; done
```

#### 方案 B：Kubernetes（示例）

> 具体 ConfigMap/Volume 名称以集群实际为准；核心是“更新配置源 + 重启 API Pod”。

```bash
# 以 ConfigMap 承载 prod.json 为例
kubectl -n digital-earth create configmap digital-earth-config \
  --from-file=prod.json=config/prod.json \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n digital-earth rollout restart deployment/digital-earth-api
kubectl -n digital-earth rollout status deployment/digital-earth-api
```

### 4.4 流量突增处理（演练/实战）

**目标：保护 API 稳定性，优先保核心读接口，避免全站雪崩。**

建议顺序：

1) 先看是否是“正常流量增长”还是“异常攻击”
2) 优先在边缘（CDN/WAF/Ingress）挡掉明显异常
3) API 侧调整：
   - 对 tiles 放宽上限（如果缓存命中高且成本可控）
   - 对高成本接口收紧上限
   - 必要时对攻击源加 `ip_blocklist`

**演练建议（staging 环境）：**

```bash
# 方案 1：简单 curl 并发（不依赖额外工具）
seq 1 200 | xargs -n1 -P50 -I{} curl -s -o /dev/null https://<DOMAIN>/api/v1/effects/presets

# 观察：
# - 429 是否按预期出现（带 Retry-After）
# - 5xx 是否上升（不应出现大量 503）
```

### 4.5 常见问题排查

**问题 1：突然所有用户都被限流（429）**

- 可能原因：获取到的 `client_ip` 不是用户真实 IP（例如都变成同一个 CDN/Ingress IP）
- 处理步骤：
  1) 检查边缘/Ingress 是否正确传递 `X-Forwarded-For` / `X-Real-IP`
  2) 确认 `trust_proxy_headers=true`
  3) 临时缓解：对 CDN/Ingress 出口 IP 段加 `ip_allowlist`（仅在确认可信前提下）

**问题 2：大量 503（Rate limiter unavailable）**

- 可能原因：Redis 故障或网络不通
- 临时降级（止血）：将 `api.rate_limit.enabled=false` 并重启 API（参见 5.2 降级开关）

---

## 5) 告警处理与降级开关

### 5.1 告警信号（建议最小集合）

> 监控体系（Prometheus/Grafana/云监控）可选，但信号应一致。

- API：
  - 5xx 错误率（P0/P1）
  - p95/p99 延迟（P1）
  - 429 比例异常上升（P2，可能是攻击或阈值过低）
  - 503（rate limiter unavailable）出现（P1，可能 Redis 故障）
- Nginx/Ingress：
  - upstream 5xx、连接超时（P1）
  - 缓存命中率骤降 + 回源升高（P1）
- Redis/Postgres：
  - Redis 内存/连接数异常（P1）
  - Postgres 连接耗尽/慢查询（P1）
- Cesium Ion：
  - token 用量/费用异常（P0）

### 5.2 降级开关（可执行）

> 目的：先恢复可用性，再追求功能完整。

**开关 A：关闭 API 限流（用于 Redis 故障期间止血）**

1) 修改 `config/<env>.json`：

```json
{
  "api": {
    "rate_limit": {
      "enabled": false
    }
  }
}
```

2) 重启 API（参见 4.3）

**风险提示**：关闭限流可能放大攻击/突增流量影响，需配合边缘限流/封禁。

**开关 B：快速封禁攻击源（API 侧）**

```json
{
  "api": {
    "rate_limit": {
      "ip_blocklist": ["203.0.113.0/24", "2001:db8::/32"]
    }
  }
}
```

**开关 C：提高缓存 TTL（降低回源，牺牲时效）**

- 修改 `deploy/nginx/sites-enabled/app.conf` 中 tiles 的 `proxy_cache_valid`（示例：1h → 12h）
- 重载 Nginx（参见 3.2）

### 5.3 告警处理 Runbook（流程）

**收到告警 → 5 分钟内完成：定位影响面 + 初步止血**

1) 影响面确认
   - 是否全站？仅 `/api/v1/*`？仅 tiles？
   - 用户侧症状：白屏/地球不出图/数据不刷新/请求大量 429
2) 快速检查
   - K8s：`kubectl -n digital-earth get pods`（CrashLoop/重启次数）
   - API：`kubectl -n digital-earth logs deploy/digital-earth-api --tail=200`
   - Nginx：`docker compose ... logs nginx --tail=200`（如使用）
3) 根据症状选择分支处理
   - token 盗刷：走 2.3
   - 429 激增：走 4.4/4.5
   - 503（限流器不可用）：走 5.2 开关 A + 查 Redis
   - 缓存异常/回源风暴：走 3.5
4) 恢复验证
   - 关键接口恢复（200/304），5xx 回落
   - 观察 15 分钟，确认无二次告警

---

## 6) 应急响应流程（必须执行）

### 6.1 事件分级（建议）

- **P0（重大事故）**：影响核心功能/大面积用户；或发生费用/安全事件（如 token 盗刷）
- **P1（严重）**：部分功能不可用、持续 5xx/超时、Redis/Postgres 故障
- **P2（一般）**：局部异常、429 升高、缓存不一致但可绕过
- **P3（轻微）**：单点告警、无用户影响

### 6.2 角色分工（最小 3 人）

- **IC（Incident Commander）**：统一指挥、定优先级、对外同步
- **Ops**：执行变更（限流/缓存/回滚/扩容），收集系统信号
- **Dev/Owner**：提供根因分析与修复方案，判断是否需要热修

### 6.3 标准时间线（SOP）

0–5 分钟：

- 建立事件群/工单（记录开始时间、级别、影响面）
- 决定是否升级 P0/P1
- 立即执行止血（降级开关/封禁/回滚/扩容）

5–30 分钟：

- 稳定服务（错误率下降、延迟恢复）
- 确认用户侧恢复（抽样访问、关键链路检查）
- 持续同步（每 10–15 分钟一次）

30 分钟–结束：

- 根因定位与永久修复计划
- 逐步回退临时降级（恢复正常阈值与缓存策略）

事后（T+24h 内）：

- 输出复盘：时间线、根因、影响、处置、改进项（含 owner 与截止日期）

### 6.4 演练验收（模拟盗刷 / 流量突增）

**演练 A：模拟盗刷（staging）**

- 输入：准备一个“旧 token”、一个“新 token”
- 可选：用旧 token 做受控并发请求，模拟“用量异常”（仅用于演练环境）

```bash
# 示例：并发调用 Cesium Ion API（以官方接口为准）
seq 1 200 | xargs -n1 -P20 -I{} \
  curl -s -o /dev/null -H "Authorization: Bearer <OLD_TOKEN>" https://api.cesium.com/v1/me
```

- 过程：
  1) 假设收到 P0 告警（用量异常）
  2) 按 2.3 完成轮换并上线新 token
  3) 观察窗口内确认用量恢复正常
- 通过标准：
  - 10 分钟内完成止血（新 token 上线并验证）
  - 形成事件记录与复盘草稿

**演练 B：流量突增（staging）**

- 输入：对 `/api/v1/effects/presets` 发起并发请求（参见 4.4）
- 过程：
  1) 观察 429/延迟/5xx
  2) 调整 `api.rate_limit.rules`（提高或收紧）并重启 API
  3) 如 Redis 不稳，演练降级开关 A（关闭限流）并配合边缘限制
- 通过标准：
  - 关键接口无大面积 5xx
  - 调整阈值后，429/延迟符合预期

