# Digital Earth - 数字地球气象可视化平台

> 项目级 Claude Code 指令文档 | 确保开发不偏离 PRD/SPEC

---

## 一、项目概述

双平台气象可视化系统：Web (CesiumJS) + UE5 客户端，支持全球/区域/事件三种模式。

**核心场景**：
1. 点位仰视天空 - 气象图层叠加
2. 区域事件模式 - 积雪/风险可视化
3. UE 飞行模拟 - 灾害天气特效

---

## 二、技术栈（固定）

| 层级 | 技术 |
|------|------|
| Web 前端 | CesiumJS + TypeScript + Tailwind CSS |
| UE 客户端 | UE5.3+ + Cesium for Unreal + Niagara |
| 后端 | Python (FastAPI) + PostgreSQL 15+ + Redis 7+ |
| 数据处理 | Python 3.11+ + xarray + ecCodes |
| 部署 | Docker + Kubernetes + CDN |

---

## 三、目录结构

```
Digital-earth/
├── apps/
│   ├── web/          # Web 前端 (CesiumJS)
│   ├── api/          # 后端 API (FastAPI)
│   └── ue-client/    # UE5 客户端
├── services/
│   └── data-pipeline/ # 数据处理管线
├── packages/         # 共享代码包
├── infra/            # K8s/Docker 配置
├── docs/             # 规范文档
└── scripts/          # 工具脚本
```

---

## 四、关键约束（来自 PRD/SPEC）

### 4.1 必须遵守
- **无登录系统**：公开读接口无鉴权，仅编辑接口需鉴权
- **归因与免责**：必须展示数据来源归因和免责声明
- **API 统一前缀**：所有 HTTP API 使用 `/api/v1/`
- **色标一致性**：Web/UE 使用后端下发的 `legend.json`

### 4.2 性能指标
- 首屏加载 ≤3s（CDN 加速）
- 瓦片请求 ≤200ms（P95）
- 60fps 渲染（Web/UE）

### 4.3 数据源
- ECMWF：GRIB2 格式，6小时更新
- CLDAS：NetCDF 格式，1小时更新

---

## 五、开发规范速查

### 5.1 命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| React 组件 | PascalCase | `LayerPanel.tsx` |
| TS 工具函数 | camelCase | `formatTemp.ts` |
| Python 模块 | snake_case | `data_processor.py` |
| UE Blueprint | BP_ 前缀 | `BP_WeatherCtrl` |
| UE Widget | WBP_ 前缀 | `WBP_FlightHUD` |

### 5.2 Git 分支
```
feature/<issue-id>-<short-desc>
fix/<issue-id>-<short-desc>
release/v<major>.<minor>.<patch>
```

### 5.3 Commit 格式
```
<type>(<scope>): <subject>

type: feat|fix|docs|refactor|test|chore
scope: web|ue|api|data
```

---

## 六、状态机命名映射

| 开发状态名 | 产品/界面文案 | 说明 |
|------------|---------------|------|
| Global | 全球视图 | 默认模式，全球气象概览 |
| Local | 点位仰视 | 单点天空视角 |
| Event | 区域事件 | 积雪/风险等事件可视化 |
| LayerGlobal | 图层全球 | 特定图层的全球展示 |

---

## 七、API 响应规范

**成功响应**：HTTP 200，直接返回数据
```json
{ "temperature": 25.5, "humidity": 60 }
```

**错误响应**：HTTP 4xx/5xx
```json
{
  "error_code": 40001,
  "message": "Invalid parameter",
  "trace_id": "abc123"
}
```

**透传规则**：Header `X-Trace-Id` 贯穿前后端

---

## 八、测试要求

| 模块 | 覆盖率 | 框架 |
|------|--------|------|
| 核心业务 | ≥90% | Vitest / pytest |
| 工具函数 | ≥80% | - |
| UI 组件 | ≥70% | React Testing Library |

**必须包含**：单元测试 + 集成测试 + 合同测试

---

## 九、关联文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 开发规范 | `docs/dev-spec.md` | 完整开发标准 |
| UI 设计规范 | `docs/ui-design-spec.md` | 设计系统与组件 |
| PRD | `DigitalEarth_PRD_SPEC_Backlog_v1.0/` | 产品需求 |
| SPEC | `DigitalEarth_PRD_SPEC_Backlog_v1.0/` | 技术规格 |
| Backlog | `DigitalEarth_PRD_SPEC_Backlog_v1.0/` | 任务清单 |

---

## 十、开发检查清单

开始任何功能开发前，确认：

- [ ] 已阅读相关 Epic/Story 的 Issue
- [ ] 已理解 PRD 中的功能定义
- [ ] 已确认 SPEC 中的技术约束
- [ ] 已遵循 `docs/dev-spec.md` 代码规范
- [ ] UI 开发已参考 `docs/ui-design-spec.md`

---

*版本: v1.0 | 更新日期: 2026-01-15*
