# K8s Secrets（模板）

本目录用于存放 **Kubernetes Secret 的模板文件**，便于运维/发布时按规范注入 secrets。

约束：

- **禁止**将真实 token/密码提交到 Git（包括 `stringData`/`data` 中的实际值）
- 只提交 `*.secret.template.yaml`（模板），真实 Secret 请在部署环境创建/更新

## UE：Cesium ion Access Token（独立 Token + 最小权限）

- 环境变量名：`DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN`
- 用途：UE5 客户端（Cesium for Unreal）读取 ion 资产（tiles/terrain/imagery）
- 权限原则：仅 `assets:read` + 资产白名单（Selected assets），严禁 admin/private scopes

模板文件：

- `ue-cesium-ion-token.secret.template.yaml`

创建/更新（示例）：

```bash
kubectl -n digital-earth create secret generic digital-earth-ue-cesium \
  --from-literal=DIGITAL_EARTH_UE_CESIUM_ION_ACCESS_TOKEN='<UE_TOKEN>' \
  --dry-run=client -o yaml | kubectl apply -f -
```
