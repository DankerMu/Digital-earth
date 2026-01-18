# [ST-0010] 成本告警：带宽/回源/对象存储请求数

作为负责人，我希望及时发现流量异常和成本风险。本方案基于 Prometheus + Alertmanager（Prometheus Operator / kube-prometheus-stack 常见部署）提供：

- **监控指标**：带宽（出口流量）、回源请求（API/Origin 请求）、对象存储请求数（需接入对应 exporter/业务指标）
- **阈值告警**：支持邮件（SMTP）与短信（Webhook→短信网关）两类通知
- **紧急降级开关**：通过 K8s ConfigMap 热更新（目标：**5 分钟内生效**）

> 相关清单：
> - 告警/路由配置：`infra/k8s/monitoring/cost-alerts.yaml`
> - 降级开关示例：`infra/k8s/monitoring/emergency-degrade-switch.yaml`

---

## 1) 指标口径与数据源

### 1.1 带宽（出口流量）

默认使用 Kubernetes/cAdvisor 通用指标估算 Digital Earth 命名空间出口带宽：

- **指标**：`container_network_transmit_bytes_total{namespace="digital-earth"}`
- **计算**：`sum(rate(...[5m])) * 8 / 1e6` → Mbps

说明：
- 该口径反映的是 **Pod 出口网络流量**（与 CDN 边缘下行不完全等价），但能快速捕捉“回源流量突增/异常爬虫/接口爆炸”等成本风险信号。
- 如已接入 CDN/云厂商带宽指标（CloudWatch/阿里云/腾讯云 exporter），建议在后续将告警表达式替换为 **CDN 计费口径**。

### 1.2 回源请求数（Origin Requests）

默认用 Ingress Controller 的请求指标近似回源请求数（以 NGINX Ingress 为例）：

- **指标**：`nginx_ingress_controller_requests{namespace="digital-earth", service="digital-earth-api"}`
- **计算**：`sum(rate(...[5m]))` → 请求/秒（rps）

> 如果实际使用 Traefik 或云厂商网关，请按实际 exporter 的指标名/label 调整表达式。

### 1.3 对象存储请求数（Object Storage Requests）

对象存储请求数强依赖“你接入了哪个 exporter/指标源”，本仓库提供两种推荐接法：

1. **云厂商指标 exporter（推荐）**：例如 CloudWatch exporter / YACE，将 `NumberOfRequests` 拉进 Prometheus。
2. **业务侧自定义指标**：由 API/数据管线在发起对象存储请求时打点 `digital_earth_object_storage_requests_total`（Counter）。

告警规则文件中默认使用 **业务侧自定义指标名**（可按实际替换）。

---

## 2) 告警规则（默认阈值）

告警规则定义在 `infra/k8s/monitoring/cost-alerts.yaml` 的 `PrometheusRule` 内，包含（可按环境调整）：

- **带宽告警**
  - `DigitalEarthEgressBandwidthHigh`：出口带宽持续高于阈值（warning）
  - `DigitalEarthEgressBandwidthCritical`：出口带宽持续高于阈值（critical）
- **回源请求告警**
  - `DigitalEarthOriginRequestRateHigh`：API/Origin 请求 rps 超阈值（warning）
  - `DigitalEarthOriginRequestRateCritical`：API/Origin 请求 rps 超阈值（critical）
- **对象存储请求告警**
  - `DigitalEarthObjectStorageRequestRateHigh`：对象存储请求 rps 超阈值（warning）
  - `DigitalEarthObjectStorageRequestRateCritical`：对象存储请求 rps 超阈值（critical）

> 阈值建议：先用保守值跑起来，观察 1～2 周基线后再校准（结合业务峰值、成本预算与容灾策略）。

---

## 3) 通知渠道（邮件/短信）

告警通知路由定义在同一个文件的 `AlertmanagerConfig` 内：

- `severity=warning` → 邮件（Email）
- `severity=critical` → 邮件 + 短信（Webhook→短信网关）

落地时需要准备：

- SMTP 账号（或企业邮箱 SMTP）
- 短信网关 Webhook（可对接企业内部告警平台/短信服务）

注意事项：
- 本仓库不提交任何敏感信息。SMTP 认证信息建议用 `Secret` 管理，并在 `AlertmanagerConfig` 中引用。
- 如果集群的 Alertmanager 未启用跨命名空间选择器（`alertmanagerConfigNamespaceSelector`），请把 `AlertmanagerConfig` 应用到 **Alertmanager 所在命名空间**（常见为 `monitoring`）。

---

## 4) 紧急降级开关（5 分钟内生效）

降级开关建议以 **ConfigMap + 挂载文件** 的形式注入到应用（API/Web/网关均可读取），并保证：

- 配置文件 **热更新**（无需重启 Pod）
- 应用侧 **轮询/监听** 配置变化（建议 ≤60s 周期），从而满足“5 分钟内生效”

示例配置见：`infra/k8s/monitoring/emergency-degrade-switch.yaml`，包含两类开关：

- `features.tiyun.enabled`：关闭“体云”（高消耗效果/资源）
- `features.zoom.max_level`：限制最大 zoom（降低瓦片/回源请求压力）

> Kubernetes ConfigMap 挂载到 Pod 的文件会在短时间内自动更新（受 kubelet 同步周期影响，通常 1～2 分钟级别）。应用侧轮询/文件监听后整体可在 5 分钟内生效。

---

## 5) 测试与验证步骤（必须）

### 5.1 静态检查（本地）

1) 确认 YAML 可解析（需要 `python` + `pyyaml`）：

```bash
python3 - <<'PY'
import yaml
from pathlib import Path

paths = [
  Path("infra/k8s/monitoring/cost-alerts.yaml"),
  Path("infra/k8s/monitoring/emergency-degrade-switch.yaml"),
]
for p in paths:
  docs = list(yaml.safe_load_all(p.read_text(encoding="utf-8")))
  assert docs, f"empty yaml: {p}"
print("ok:", ", ".join(str(p) for p in paths))
PY
```

### 5.2 集群验证（告警可触发）

> 以下以 kube-prometheus-stack 为例，实际命名空间/CRD 可能不同，请按集群情况调整。

1) 应用告警与通知配置：

```bash
kubectl apply -f infra/k8s/monitoring/cost-alerts.yaml
```

2) 确认 Prometheus 已加载规则：

```bash
kubectl -n monitoring get prometheusrules
kubectl -n monitoring describe prometheusrule digital-earth-cost-alerts
```

3) 触发验证（任选其一）：

- **方法 A（推荐，安全）**：在 Grafana/Prometheus UI 中临时把阈值调低（或使用短窗口），观察告警进入 `Pending`→`Firing`。
- **方法 B（端到端）**：向 API 施加压测/回放流量（在非生产环境），观察 `DigitalEarthOriginRequestRate*` 告警触发，并确认邮件/短信收到通知。

### 5.3 集群验证（降级开关 5 分钟内生效）

1) 应用 ConfigMap：

```bash
kubectl apply -f infra/k8s/monitoring/emergency-degrade-switch.yaml
```

2) 修改开关并观察生效时间（不重启 Pod）：

```bash
kubectl -n digital-earth edit configmap digital-earth-emergency-degrade
```

3) 验证方式：
- 若应用实现了配置轮询/监听：在 5 分钟内观察“体云关闭/zoom 限制”行为变化
- 若尚未接入读取逻辑：需要先把该 ConfigMap 挂载到 Pod 并在应用侧增加读取/轮询（建议轮询周期 ≤60s）
