# 性能压测（瓦片并发 / CDN 命中 / 源站回源）

本目录提供一个可重复执行的 **k6** 压测方案，用于上线前评估公网访问下的瓦片服务承载能力：

- 模拟瓦片并发请求（ramp-up / sustained / spike）
- 从响应头推断 CDN 命中率（HIT/MISS/UNKNOWN）
- 估算源站回源带宽（按 MISS 响应体积估算）
- 自动生成 `report.json` / `report.md` / `report.html` 报告与上线参数建议

## 安全说明

- 脚本只做 `GET` 请求，不会写入/修改任何数据
- 默认压测配置偏保守；对 `production` 环境必须显式加 `--allow-production`
- 请在压测时同时观察：CDN 监控面板、源站带宽/连接数/CPU/内存、错误日志

## 依赖

- 安装 k6：`https://k6.io/docs/get-started/installation/`
- 本机 Python 3.11+（用于生成报告）

## 配置

环境配置在 `infra/loadtest/config/`：

- `staging.json`
- `production.json`

需要根据实际服务修改：

- `base_url`：瓦片公网访问域名（建议为 CDN 域名）
- `tile.path_template`：瓦片路径模板（支持 `{z}` `{x}` `{y}`，可增加自定义占位符）
- `tile.zooms/x_range/y_range`：请求范围（推荐用“真实热门区域”范围，避免大量 404）
- `headers`：如果需要鉴权（如 token / API key），在这里加自定义 header

## 运行

从仓库根目录执行：

```bash
./infra/loadtest/run.sh --env staging --scenario ramp
```

生产环境必须显式允许：

```bash
./infra/loadtest/run.sh --env production --scenario sustained --allow-production
```

输出目录默认在 `infra/loadtest/results/<env>/<timestamp>-<scenario>/`，包含：

- `summary.json`：k6 `--summary-export` 原始结果
- `report.json`：结构化汇总
- `report.md` / `report.html`：可读报告

## 指标解释（简要）

- **CDN Hit Rate**：基于响应头推断（优先 `cf-cache-status` / `x-cache` / `x-cache-hits` / `age`）
- **Origin Bandwidth (est)**：将 `MISS` 响应体积视作“回源”体积估算
- **Origin Bandwidth (cons.)**：将 `MISS + UNKNOWN` 视作回源的保守估算

> 注意：不同 CDN 的头部含义略有差异；如果大量 `UNKNOWN`，可在 config 中补充 `cdn.hit_header_name` 规则。

