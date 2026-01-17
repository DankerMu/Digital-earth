# 公网域名与 TLS（cert-manager）

本文档说明如何在 Kubernetes 上为 Digital Earth 配置公网域名、HTTPS 强制跳转、以及基于 cert-manager 的 TLS 证书自动签发与续期。

## 前置条件

- 已安装 Ingress Controller（任选其一）
  - NGINX Ingress Controller（`ingressClassName: nginx`）
  - Traefik v2（`ingressClassName: traefik`，并已安装 CRDs：`Middleware` 等）
- 已安装 cert-manager
- 公网域名已解析到 Ingress Controller 暴露的公网入口（LoadBalancer IP / CDN / 反向代理）

> 建议先用 Let’s Encrypt Staging 走通流程，确认 OK 后再切换 Production，避免触发频率限制。

## 1) 创建命名空间

```bash
kubectl apply -f infra/k8s/namespace-digital-earth.yaml
```

## 2) 配置 ClusterIssuer（证书签发器）

根据 Ingress Controller 选择对应模板，并把 `email` 改成自己的邮箱：

- NGINX：
  - `infra/k8s/cert-manager/cluster-issuer-letsencrypt-staging-nginx.yaml`
  - `infra/k8s/cert-manager/cluster-issuer-letsencrypt-prod-nginx.yaml`
- Traefik：
  - `infra/k8s/cert-manager/cluster-issuer-letsencrypt-staging-traefik.yaml`
  - `infra/k8s/cert-manager/cluster-issuer-letsencrypt-prod-traefik.yaml`

```bash
# 示例：先上 staging
kubectl apply -f infra/k8s/cert-manager/cluster-issuer-letsencrypt-staging-nginx.yaml
```

## 3) 应用 Ingress（TLS + 强制 HTTPS 跳转）

### 方案 A：NGINX Ingress

1. 选择模板（是否启用 HSTS）
   - 不启用 HSTS：`infra/k8s/ingress/nginx/digital-earth-ingress.yaml`
   - 启用 HSTS：`infra/k8s/ingress/nginx/digital-earth-ingress-hsts.yaml`
2. 修改域名 `example.com`、以及后端 Service 名称/端口（如需要）
3. 如需先走 staging，把 `cert-manager.io/cluster-issuer` 改为 `letsencrypt-staging-nginx`

```bash
kubectl apply -f infra/k8s/ingress/nginx/digital-earth-ingress.yaml
```

### 方案 B：Traefik Ingress

Traefik 的 HTTPS 跳转与 HSTS 通过 `Middleware`（CRD）实现：

1. 应用中间件
```bash
kubectl apply -f infra/k8s/ingress/traefik/middleware-redirect-to-https.yaml
# 可选：HSTS
kubectl apply -f infra/k8s/ingress/traefik/middleware-secure-headers-hsts.yaml
```

2. 选择 Ingress 模板（HTTP/HTTPS 分离）
   - HTTP（负责 80→443 跳转）：`infra/k8s/ingress/traefik/digital-earth-ingress-http.yaml`
   - HTTPS（不启用 HSTS）：`infra/k8s/ingress/traefik/digital-earth-ingress-https.yaml`
   - HTTPS（启用 HSTS）：`infra/k8s/ingress/traefik/digital-earth-ingress-https-hsts.yaml`

同样需要把 `example.com`、Service 名称/端口按实际修改；如需先走 staging，把 `cert-manager.io/cluster-issuer` 改为 `letsencrypt-staging-traefik`。

```bash
kubectl apply -f infra/k8s/ingress/traefik/digital-earth-ingress-http.yaml
kubectl apply -f infra/k8s/ingress/traefik/digital-earth-ingress-https.yaml
```

## 4) 验证签发结果

```bash
kubectl -n digital-earth get certificate,challenge,order
kubectl -n digital-earth describe certificate digital-earth-tls
kubectl -n digital-earth get secret digital-earth-tls
```

正常情况下：
- `Certificate` 状态为 `Ready=True`
- Ingress `tls.secretName` 对应的 Secret 已生成/更新
- cert-manager 会在到期前自动续期（无需手工操作）

## 5) HSTS 注意事项（可选）

HSTS 会让浏览器在一段时间内强制使用 HTTPS（即使你把 Ingress 改回 HTTP 也不会立刻生效）。建议：

- 只在确认 HTTPS 稳定后启用
- 先在测试域名验证，再用于生产主域
