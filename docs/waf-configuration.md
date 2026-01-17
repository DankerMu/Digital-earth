# WAF 基础防护配置（NGINX Ingress + ModSecurity/OWASP CRS）

> 版本: v1.0 | 更新日期: 2026-01-17

本文档面向运维/发布人员，说明如何在 Kubernetes 上为 Digital Earth 开启 **基础 WAF 防护**（SQLi / XSS / 扫描探测），并记录拦截日志，支持（可选）针对异常 UA/IP 的短时封禁。

## 目标（验收口径）

- 常见攻击/扫描（SQLi/XSS/敏感路径探测）被拦截（HTTP 403）。
- 正常访问不受影响（首页与 API 正常返回）。
- 拦截日志可查询（可通过 `kubectl logs` 或日志系统检索）。

## 方案选择与范围

本仓库当前提供两套 Ingress 示例：

- **NGINX Ingress**：可直接启用 ModSecurity + OWASP CRS，适合做基础 WAF（推荐）。
- **Traefik**：默认不内置应用层 WAF（SQLi/XSS 检测需要额外插件/外部 WAF），本任务仅提供 NGINX Ingress 的 WAF 配置；Traefik 可继续使用现有 HTTPS/HSTS/中间件能力。

## 前置条件

- 已部署 NGINX Ingress Controller（`ingressClassName: nginx`）
- 已存在 Digital Earth Ingress（示例见 `infra/k8s/ingress/nginx/digital-earth-ingress.yaml`）
- 集群已具备日志采集/查询能力（至少能 `kubectl logs` 查看 controller 日志；生产建议接入 Loki/ELK/Cloud Logging）

## 1) 启用 WAF（Controller 侧）

WAF 规则与日志配置在 `infra/k8s/waf-rules.yaml` 中，以 `ConfigMap` 的形式提供：

- `enable-modsecurity: "true"`：启用 ModSecurity
- `enable-owasp-modsecurity-crs: "true"`：启用 OWASP CRS
- `modsecurity-snippet`：自定义规则 + 审计日志输出（JSON → stdout）

注意：该文件内的 `ConfigMap` 名称使用了常见的 `ingress-nginx-controller`（位于 `ingress-nginx` 命名空间），但实际名称可能因安装方式（Helm/kustomize）不同而不同。

建议做法（安全）：

1. 找到你的 controller ConfigMap
```bash
kubectl -n ingress-nginx get configmap
```

2. 将 `infra/k8s/waf-rules.yaml` 中 `data` 的相关键合并到实际 controller ConfigMap（推荐用 GitOps/Helm values 管理）

示例（直接 apply，适用于你确认 ConfigMap 名称一致的场景）：
```bash
kubectl apply -f infra/k8s/waf-rules.yaml
```

## 2) 启用 WAF（Ingress 侧）

本仓库已在 NGINX Ingress 示例中加入 WAF 注解（见下列文件）：

- `infra/k8s/ingress/nginx/digital-earth-ingress.yaml`
- `infra/k8s/ingress/nginx/digital-earth-ingress-hsts.yaml`

关键注解：

- `nginx.ingress.kubernetes.io/enable-modsecurity: "true"`
- `nginx.ingress.kubernetes.io/enable-owasp-core-rules: "true"`
- `nginx.ingress.kubernetes.io/modsecurity-transaction-id: "$request_id"`（便于用同一 ID 关联 access log 与 WAF 审计日志）

应用示例：
```bash
kubectl apply -f infra/k8s/namespace-digital-earth.yaml
kubectl apply -f infra/k8s/ingress/nginx/digital-earth-ingress.yaml
```

## 3) 规则说明（基础防护）

`infra/k8s/waf-rules.yaml` 的 `modsecurity-snippet` 中包含：

- **扫描探测拦截**：阻断 `/.env`、`/.git/`、`/wp-login.php`、`/phpmyadmin` 等典型探测路径（rule id `1001000`）
- **SQLi 拦截**：阻断明显的 SQL 注入关键字组合（rule id `1001001`）
- **XSS 拦截**：阻断明显的脚本注入特征（rule id `1001002`）
- **（可选）异常 UA/IP 短时封禁**：
  - 命中 `sqlmap/nikto/...` 等 UA 直接拦截并累计计数（rule id `1001100`）
  - 同一 IP 在 10 分钟窗口内累计达到阈值后短时封禁（rule id `1001101`）

> 提示：OWASP CRS 本身也会提供更全面的 SQLi/XSS 检测。本仓库的自定义规则用于覆盖“最常见攻击流量”与“验收可复现”的最小集合，且尽量降低误伤风险。

## 4) 日志查询（拦截可追踪）

WAF 审计日志使用 JSON 输出到 controller stdout（`SecAuditLog /dev/stdout` + `SecAuditLogFormat JSON`）。

常用查询：

```bash
# 查看 ingress-nginx controller 日志（不同安装方式 deployment 名称可能不同）
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller

# 过滤自定义规则 id（示例：扫描探测）
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller | rg '1001000'
```

如日志为可解析 JSON（取决于日志聚合与换行策略），可结合 `jq` 做结构化查询：

```bash
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller | jq -r 'select(.transaction.messages != null) | .transaction.unique_id'
```

## 5) 验证步骤（必做）

将 `<BASE_URL>` 替换为你的站点（例如 `https://example.com`），并确保 Ingress 已生效。

可选：使用脚本快速验证（推荐 CI/运维自检）：

```bash
./scripts/waf-smoke-test.sh <BASE_URL>
```

### 5.1 正常访问不受影响

```bash
curl -s -o /dev/null -w "%{http_code}\n" <BASE_URL>/
curl -s -o /dev/null -w "%{http_code}\n" <BASE_URL>/api/v1
```

期望：返回 `200/301/302` 等正常状态（按实际路由而定），不应被 `403` 拦截。

### 5.2 模拟扫描探测（应被拦截）

```bash
curl -s -o /dev/null -w "%{http_code}\n" <BASE_URL>/.env
curl -s -o /dev/null -w "%{http_code}\n" <BASE_URL>/.git/config
```

期望：`403`

### 5.3 模拟 SQLi（应被拦截）

```bash
curl -s -o /dev/null -w "%{http_code}\n" "<BASE_URL>/api/v1/search?q=1%20union%20select%201,2,3"
```

期望：`403`

### 5.4 模拟 XSS（应被拦截）

```bash
curl -s -o /dev/null -w "%{http_code}\n" "<BASE_URL>/?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
```

期望：`403`

### 5.5 验证拦截日志可查询

```bash
kubectl -n ingress-nginx logs deploy/ingress-nginx-controller | rg 'WAF:'
```

期望：能看到 `WAF:` 开头的 `msg`，并包含对应 rule id（如 `1001001`）。

## 6) 上线建议与回滚

### 6.1 误报处理（推荐流程）

1. 先在预发环境运行 24h
2. 观察拦截日志中是否存在误报（重点关注业务高频接口）
3. 需要放行时，优先按 **路径/参数** 做更精细规则，而不是整体关闭 WAF

### 6.2 快速回滚

- Ingress 侧：移除以下注解并重新 apply
  - `nginx.ingress.kubernetes.io/enable-modsecurity`
  - `nginx.ingress.kubernetes.io/enable-owasp-core-rules`
- Controller 侧：移除/回滚 `enable-modsecurity` / `enable-owasp-modsecurity-crs` / `modsecurity-snippet`

> 注意：回滚后仍建议保留日志检索能力，以便持续观察扫描流量与攻击面。
