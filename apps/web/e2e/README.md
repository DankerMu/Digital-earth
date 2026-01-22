# Web E2E Tests (Playwright)

本目录提供 Web 端核心流程的端到端测试（Issue #178）。

## 运行

1) 安装依赖

`pnpm install`

2) 安装 Playwright 浏览器

- macOS / Windows：
  - `pnpm --filter web exec playwright install`
- Linux（CI 推荐）：
  - `pnpm --filter web exec playwright install --with-deps`

3) 执行 E2E

`pnpm --filter web test:e2e`

## 用例

### 流程 A：点位 -> 仰视 -> 锁层 -> 层全局

- 双击地图进入 Local 模式（出现 `LocalInfoPanel`）
- 切换相机视角为「仰视」
- 点击「锁定当前层」进入 Layer Global 模式
- 校验壳层（LayerGlobal Shell）已生效
- 保存截图（作为报告附件）

### 流程 B：事件 -> 风险点 -> 特效触发

- 在事件列表选择一个事件进入 Event 模式
- 校验事件 polygon 已渲染
- 校验风险点已加载
- 点击风险点打开详情弹窗
- 打开「灾害演示」并点击「播放」触发特效
- 保存截图（作为报告附件）

## Mock 策略

- E2E 会在浏览器侧拦截 `/config.json` 与 `/api/v1/**`（见 `apps/web/e2e/mocks.ts`），避免依赖后端服务，提升 CI 稳定性。
- 可按需扩展 mock 数据，或替换为真实后端环境。

