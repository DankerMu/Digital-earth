# 数字地球气象可视化平台 - 开发规范文档

> 版本: v1.0 | 更新日期: 2026-01-14

---

## 一、文档概述

### 1.1 目的与范围

统一团队开发标准，确保代码质量和协作效率。

**适用人员**：全栈、前端、UE、后端、数据工程师

### 1.2 技术栈

| 层级 | 技术 |
|------|------|
| Web 前端 | CesiumJS + TypeScript + Tailwind CSS |
| UE 客户端 | UE5 + Cesium for Unreal + Niagara |
| 后端 | Python (FastAPI)（最终选型） + PostgreSQL + Redis |
| 数据处理 | Python + xarray + ecCodes |
| 部署 | Docker + Kubernetes + CDN |

### 1.3 关联文档

- PRD：产品需求文档
- SPEC：技术规格文档
- Backlog：任务清单
- `docs/ui-design-spec.md`：UI/UX 设计规范

---

## 二、项目结构

### 2.1 根目录

| 目录 | 说明 |
|------|------|
| `apps/web/` | Web 前端 |
| `apps/ue-client/` | UE 客户端 |
| `apps/api/` | 后端 API |
| `services/data-pipeline/` | 数据处理 |
| `packages/` | 共享代码包 |
| `infra/` | 基础设施配置 |
| `docs/` | 文档 |
| `scripts/` | 脚本 |

### 2.2 文件命名规范

| 类型 | 规范 | 示例 |
|------|------|------|
| React 组件 | PascalCase | `LayerPanel.tsx` |
| TS 工具函数 | camelCase | `formatTemp.ts` |
| Python 模块 | snake_case | `data_processor.py` |
| UE Blueprint | BP_ 前缀 | `BP_WeatherCtrl` |
| UE Widget | WBP_ 前缀 | `WBP_FlightHUD` |
| 配置文件 | kebab-case | `docker-compose.yml` |

### 2.3 与 SPEC 的目录映射

为保证实现与 SPEC 组件/数据管线一致，目录建议按以下方式组织（以实际仓库为准，命名需与 SPEC 保持一致）：

| SPEC 模块/域 | 建议目录 | 说明 |
|-------------|----------|------|
| 地球渲染/视图 (Viewer) | `apps/web/src/features/viewer/` | Cesium 场景、相机、基础交互 |
| 图层系统 (Layer) | `apps/web/src/features/layers/` | 图层配置、加载、渲染、开关/透明度 |
| 时间轴播放条 (Timeline) | `apps/web/src/features/timeline/` | 时间状态、播放/暂停、步进、跳转 |
| 图例/色标 (Legend) | `apps/web/src/features/legend/` | `legend.json` 渲染与默认调色板兜底 |
| 归因/数据来源 (Attribution) | `apps/web/src/features/attribution/` | 固定归因区、“数据来源”入口与免责声明 |
| Web 共享组件 | `packages/ui/` | 设计系统、组件库、Tailwind 主题 |
| 后端 API（FastAPI） | `apps/api/` | Router/Schema/Service/Repository/Model 分层 |
| tiles（二进制）接口 | `apps/api/` 或独立服务 | 读接口优先可 CDN 化，响应为二进制流 |
| 数据管线 (Data Pipeline) | `services/data-pipeline/` | 下载→预处理→插值→切片→入库/对象存储 |
| 基础设施/观测性 | `infra/` | K8s、CDN、存储、日志/链路追踪配置 |

---

## 三、代码规范

### 3.1 通用原则

- **KISS**：保持简单
- **YAGNI**：不做过度设计
- **DRY**：避免重复
- 函数 ≤50 行，嵌套 ≤3 层

### 3.2 TypeScript 命名

| 类型 | 规范 |
|------|------|
| 变量/函数 | camelCase |
| 常量 | UPPER_SNAKE_CASE |
| 类/接口/类型 | PascalCase |
| 布尔变量 | is/has/can 前缀 |

**格式**：2空格缩进，100字符行宽，单引号，必须分号

### 3.3 Python 命名

| 类型 | 规范 |
|------|------|
| 变量/函数 | snake_case |
| 常量 | UPPER_SNAKE_CASE |
| 类 | PascalCase |

**格式**：4空格缩进，88字符行宽，使用 Black + isort

### 3.4 UE C++ 命名

| 类型 | 前缀 |
|------|------|
| UObject 派生 | U |
| AActor 派生 | A |
| 结构体 | F |
| 枚举 | E |
| 布尔 | b |

### 3.5 注释要求

- 复杂算法需说明意图
- 公开 API 需文档注释
- 禁止保留注释掉的代码

---

## 四、Git 工作流

### 4.1 分支模型

| 分支 | 用途 |
|------|------|
| `main` | 生产环境 |
| `develop` | 开发主线 |
| `feature/*` | 功能开发 |
| `release/*` | 发布准备 |
| `hotfix/*` | 紧急修复 |

### 4.2 分支命名

```
feature/<issue-id>-<short-desc>
fix/<issue-id>-<short-desc>
release/v<major>.<minor>.<patch>
```

示例：`feature/EP-19-web-framework`

### 4.3 Commit 规范

格式：`<type>(<scope>): <subject>`

| Type | 说明 |
|------|------|
| feat | 新功能 |
| fix | Bug 修复 |
| docs | 文档 |
| refactor | 重构 |
| test | 测试 |
| chore | 构建/工具 |

| Scope | 说明 |
|-------|------|
| web | Web 前端 |
| ue | UE 客户端 |
| api | 后端 |
| data | 数据处理 |

### 4.4 PR 规范

- 标题：`[Issue ID] 简短描述`
- 至少 1 人 Approve
- 关键模块需 2 人 Approve
- 合并策略：Squash and Merge

---

## 五、模块开发指南

### 5.1 数据层

| 数据源 | 格式 | 更新频率 |
|--------|------|----------|
| ECMWF | GRIB2 | 6小时 |
| CLDAS | NetCDF | 1小时 |

**处理流程**：下载 → 格式转换 → 插值 → 瓦片切割 → 存储

### 5.2 后端 API

**分层架构**：Router → Schema → Service → Repository → Model

**要求**：
- RESTful 风格
- 所有 HTTP API 统一以 `/api/v1/` 为前缀（含 JSON API 与 tiles 读接口）
- 响应结构、鉴权、trace_id 规则遵循第六章
- Redis 缓存热点数据

### 5.3 Web 前端

**状态管理**：
- 全局状态：Zustand
- 服务端状态：React Query

**CesiumJS 要求**：
- 遵循 `ui-design-spec.md` 设计系统
- 注意内存管理（Entity 销毁）
- 使用 LOD 优化性能

### 5.4 UE 客户端

**蓝图 vs C++**：
- 蓝图：快速原型、UI 逻辑
- C++：性能敏感、核心系统

**Niagara 特效**：
- 粒子数量需控制
- 配置 LOD 距离

---

## 六、API 规范

### 6.1 鉴权与权限

- **公开读接口无鉴权**：以查询/读取为主的接口（如 `GET` 数据查询、元数据、tiles）默认不要求 `Authorization`。
- **编辑/管理接口需鉴权**：涉及写入、配置变更、任务触发等接口必须携带 `Authorization: Bearer <token>`。
- **鉴权失败统一返回 403**：无 token / token 无效 / 权限不足均返回 HTTP `403`，错误体见 6.3。

### 6.2 请求头与 trace_id

| Header | 必填 | 说明 |
|--------|------|------|
| Content-Type | JSON 请求必填 | `application/json` |
| Authorization | 仅鉴权接口必填 | `Bearer <token>` |
| X-Trace-Id | 可选 | 客户端可透传链路追踪 ID；服务端若未收到则生成 |

**trace_id 透传规则**：
- 若请求包含 `X-Trace-Id`，后端必须透传该值（跨服务调用保持一致）。
- 若请求未包含 `X-Trace-Id`，后端生成新的 trace_id。
- **响应头必须返回 `X-Trace-Id`**，其值与错误体中的 `trace_id` 保持一致。

### 6.3 返回结构

#### 6.3.1 成功响应

- HTTP 状态码：`200`
- 响应体：**直接返回业务数据**（不包裹 `code/message/data`）

示例：

```json
[
  {"id": "temp", "name": "温度场"},
  {"id": "precip", "name": "降水"}
]
```

#### 6.3.2 错误响应

- HTTP 状态码：非 `2xx`
- 响应体：统一 JSON

```json
{
  "error_code": 40300,
  "message": "Forbidden",
  "trace_id": "01HZX..."
}
```

### 6.4 二进制接口（tiles）例外

- tiles 接口为**二进制响应**（例如 `application/x-protobuf` / `image/png`），成功时响应体为二进制流，不遵循 6.3.1 的 JSON 结构。
- tiles 接口仍必须返回 `X-Trace-Id` 响应头；发生错误时返回 HTTP 错误码，并使用 6.3.2 的 JSON 错误体（`Content-Type: application/json`）。

### 6.5 错误码

| error_code 范围 | 对应 HTTP | 类型 |
|-----------------|----------|------|
| 40000-40999 | 400 | 客户端错误（参数、格式、业务校验） |
| 40300-40399 | 403 | 鉴权/权限错误 |
| 40400-40499 | 404 | 资源不存在 |
| 50000-50999 | 500 | 服务端错误 |

---

## 七、测试规范

### 7.1 覆盖率要求

| 模块 | 覆盖率 |
|------|--------|
| 核心业务 | ≥90% |
| 工具函数 | ≥80% |
| UI 组件 | ≥70% |

### 7.2 测试框架

| 模块 | 框架 |
|------|------|
| Web | Vitest + React Testing Library |
| 后端 | pytest |
| UE | Automation Testing Framework |

### 7.3 测试类型

- 单元测试 (70%)
- 集成测试 (20%)
- E2E 测试 (10%)

### 7.4 合同测试（Contract Testing）

- **合同来源**：后端以 OpenAPI 作为 API 合同基准；前端/客户端不得依赖未在合同中声明的字段与行为。
- **覆盖范围**：至少覆盖关键读接口、编辑/管理接口的鉴权行为（403）、以及 `X-Trace-Id` 透传规则；tiles（二进制）接口需覆盖 `Content-Type` 与错误体一致性。
- **CI 要求**：合同测试必须在 CI 中执行，通过后方可合并；任何破坏性变更必须同步更新 OpenAPI 与对应合同测试用例。

---

## 八、部署流程

### 8.1 环境

| 环境 | 触发条件 |
|------|----------|
| dev | Push to develop |
| staging | Push to release/* |
| prod | Tag v*.* |

### 8.2 CI/CD 阶段

1. Lint（代码检查）
2. Test（单元测试）
3. Build（构建）
4. Scan（安全扫描）
5. Deploy（部署）

### 8.3 发布检查清单

- [ ] 所有测试通过
- [ ] 安全扫描无高危
- [ ] 文档已更新
- [ ] 回滚方案就绪

---

## 八点五、CI 开发要点

> 本章节记录 CI 配置中常见问题及解决方案，避免重复踩坑。

### 8.5.1 Workflow 触发条件 (paths)

**问题**：`packages/**` 等宽泛路径会导致不相关的 workflow 被误触发。

**解决**：
- 每个 workflow 的 `paths` 必须精确匹配其负责的目录
- 共享包 (`packages/shared`) 有独立 CI，其他 workflow 不应包含 `packages/**`

```yaml
# ✅ 正确：精确匹配
on:
  pull_request:
    paths:
      - 'services/data-pipeline/**'

# ❌ 错误：过于宽泛
on:
  pull_request:
    paths:
      - 'services/data-pipeline/**'
      - 'packages/**'  # 会误触发，应由 ci-shared.yml 负责
```

### 8.5.2 pytest 路径配置

**问题**：`pyproject.toml` 中的相对路径在 CI `cd` 到子目录后失效。

**场景**：CI 执行 `cd services/data-pipeline && pytest tests/`，但 `pyproject.toml` 配置了相对于仓库根目录的路径。

**解决**：
- `pyproject.toml` 中避免硬编码相对路径
- CI workflow 显式指定所有 pytest/coverage 参数

```toml
# ✅ pyproject.toml - 不包含路径
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: integration tests"]

# CI workflow 显式指定
- run: |
    cd services/data-pipeline && \
    PYTHONPATH=src pytest tests/ \
      --cov=src \
      --cov-report=xml \
      --cov-fail-under=90
```

### 8.5.3 Python 模块安装方式

**问题**：`pip install -e .` 要求完整的 packages 配置，CI 环境可能缺少依赖模块。

**解决**：
- 简单场景使用 `PYTHONPATH=src` 而非 `pip install -e .`
- 需要可编辑安装时，确保 `pyproject.toml` 正确配置 `packages`

```toml
# pyproject.toml - 多模块项目
[tool.poetry]
packages = [
  {include = "ecmwf", from = "src"},
  {include = "cldas", from = "src"}
]
```

### 8.5.4 异常类型与测试同步

**问题**：代码包装异常类型后，测试期望的异常类型未同步更新。

**场景**：
```python
# 代码：ValidationError 被包装为 ValueError
except ValidationError as e:
    raise ValueError(f"Invalid config: {e}") from e

# 测试：仍期望 ValidationError → 失败
with pytest.raises(ValidationError):  # ❌
    load_config()
```

**解决**：
- 修改异常处理时，同步更新相关测试
- 保持异常类型的一致性文档化

### 8.5.5 lru_cache 暴露

**问题**：`@lru_cache` 装饰的内部函数，外部函数无法调用 `cache_clear()`。

**解决**：显式暴露缓存控制方法

```python
@lru_cache
def _get_config_cached(path: str) -> Config:
    return load_config(Path(path))

def get_config(path: str | None = None) -> Config:
    resolved = str(resolve_path(path))
    return _get_config_cached(resolved)

# 暴露 cache_clear 供测试使用
get_config.cache_clear = _get_config_cached.cache_clear  # type: ignore
```

### 8.5.6 CI 依赖安装

**问题**：`pip install -e ".[test]"` 要求 pyproject.toml 定义 `[test]` extra。

**解决**：
- 明确区分 dev dependencies 和 test extra
- CI 直接安装所需包，避免依赖 extra 定义

```yaml
# ✅ 推荐：显式安装
- run: pip install ruff pytest pytest-cov pydantic pydantic-settings pyyaml

# ⚠️ 需确保 extra 存在
- run: pip install -e ".[test]"
```

### 8.5.7 Dockerfile 与配置文件

**问题**：Dockerfile 未复制运行时需要的配置文件目录。

**解决**：确保所有运行时依赖的目录都被复制

```dockerfile
# 复制源码
COPY services/data-pipeline/src ./src
# 复制配置（容易遗漏）
COPY services/data-pipeline/config ./config
```

---

## 九、环境配置

### 9.1 软件版本

以下版本为**本项目基线版本**；如需升级（含主版本/次版本），必须评估对构建链路、运行环境与依赖兼容性的影响并记录在变更说明中。

| 软件 | 版本 |
|------|------|
| Node.js | 20.x LTS |
| Python | 3.11+ |
| PostgreSQL | 15+ |
| Redis | 7+ |
| UE | 5.3+ |

### 9.2 环境变量命名

格式：`DIGITAL_EARTH_<CATEGORY>_<NAME>`

示例：`DIGITAL_EARTH_DB_HOST`

### 9.3 本地启动

1. 克隆仓库
2. 安装依赖
3. 配置环境变量
4. 启动数据库/Redis
5. 启动开发服务器

---

*文档版本: v1.1 | 最后更新: 2026-01-15*
