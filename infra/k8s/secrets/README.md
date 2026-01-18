# K8s Secrets（模板与管理规范）

本目录只存放 **Secret 模板**（`.secret.template.yaml`），用于说明字段与命名规范；**禁止**提交任何真实 Secret。

## 文件约定

- ✅ 可提交：`*.secret.template.yaml`（仅占位符，不含真实值）
- ❌ 禁止提交：`*.secret.yaml` / `*.secret.yml`（真实密钥文件）

> 仓库已通过 `.gitignore` 忽略真实 secret 文件；请保持模板与真实文件分离。

## UE Cesium ion Token（推荐用法）

UE 打包产物属于客户端环境，Token 可能被提取，因此必须使用 **独立 Token + 最小 scopes（仅 `assets:read`）+ Selected assets**。  
详见：`docs/ue-token-security.md`

### 1) 通过模板创建（本地生成 + apply）

```bash
cp infra/k8s/secrets/ue-cesium-ion-token.secret.template.yaml \
  infra/k8s/secrets/ue-cesium-ion-token.secret.yaml

# 编辑 `ue-cesium-ion-token.secret.yaml`，填入真实 token 后下发
kubectl apply -f infra/k8s/secrets/ue-cesium-ion-token.secret.yaml
```

### 2) 通过命令行创建（避免落盘）

```bash
kubectl -n digital-earth create secret generic ue-cesium-ion-token \
  --from-literal=DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN='<TOKEN>' \
  --dry-run=client -o yaml | kubectl apply -f -
```

## 轮换/吊销

轮换原则：**先上新 token → 验证 → 再吊销旧 token**，避免业务中断。  
建议将 Token 存放在具备审计/权限控制的 Secret 管理系统中（K8s Secret、External Secrets、Vault、云 KMS 等），并建立定期轮换机制。

