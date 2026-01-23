# [ST-0109] Web 体素云 PoC（Ray-marching）

更新时间：2026-01-23

## 目标

- 验证 Web 端渲染“体积云/体素云”的可行性（CesiumJS 场景中叠加体渲染）。
- 在 **Cesium VoxelPrimitive** 与 **自研 ray-march** 之间选择可落地的技术路线。
- 读取 Volume Pack demo 数据并完成渲染。
- 输出性能报告要素：FPS / 内存 / 加载时间，并给出推荐参数（体素分辨率/步进）。

---

## 技术路线选择

### 结论：选择自研 ray-marching（Cesium PostProcessStage）

PoC 采用 **Cesium PostProcessStage** 进行屏幕空间后处理 ray-march（对体积包围盒做 ray-box 相交并积分），主要原因：

- **工程落地更直接**：无需依赖 Cesium VoxelPrimitive 的特定数据结构/管线，直接对现有 Cesium 渲染结果做合成。
- **可控性强**：步进/最大步数/密度参数完全由业务侧控制，便于做性能自适应策略。
- **数据管线复用**：可直接复用 `Volume Pack (VOLP)` 解码结果（`apps/web/src/lib/volumePack.ts`）。

### 为什么不优先使用 Cesium VoxelPrimitive

- VoxelPrimitive 更贴近“体素数据可视化”的原生渲染路径，但 PoC 阶段需要更多确认项：
  - 数据组织/纹理格式（3D texture / atlas / brick）与浏览器兼容性（WebGL1/2 差异）
  - 与现有图层系统的合成顺序/透明度策略
  - 对不同设备的性能上限与降级方案
- 因此本 PoC 先用可控的 ray-march 验证效果与性能边界。

---

## 实现概述

### 核心模块

- `apps/web/src/features/voxelCloud/VoxelCloudRenderer.ts`
  - 负责：加载 VOLP、构建 2D atlas、创建/管理 `PostProcessStage`、提供 load metrics 与推荐参数。
- `apps/web/src/features/voxelCloud/shader.ts`
  - 后处理 fragment shader：ray-box 相交 + 体积密度积分（吸收模型，PoC 先做白色云体混合）。
- `apps/web/src/features/voxelCloud/VoxelCloudPocPage.tsx`
  - Demo 页面：控制参数、显示 FPS/内存/加载耗时。

### 数据格式与纹理策略

- 输入：Volume Pack（`VOLP`），shape 为 `[levels, lat, lon]`。
- GPU 采样：使用 **2D texture atlas**（将每个 level 切片拼成网格），避免依赖 3D texture 支持。
- 云体包围盒：从 `header.bbox` 推导，使用 bbox 中心点的 ENU frame 构造轴向（east/north/up）并在 shader 中做坐标变换。

---

## Demo 使用方式

### 1) 生成/更新 demo 数据（可选）

PoC 已提交一份 demo 文件：`apps/web/public/volumes/demo-voxel-cloud.volp`。

如需重新生成：

```bash
pnpm -C apps/web generate:voxel-cloud-demo
```

### 2) 运行 PoC 页面

```bash
pnpm -C apps/web dev
```

打开：

- `http://localhost:5173/?poc=voxel-cloud`

操作：

- 点击 **Load**（默认加载 `/volumes/demo-voxel-cloud.volp`）
- 调整 `Step (voxels)` / `Max steps` / `Density ×` / `Extinction`
- 在面板中查看：FPS、JS heap、加载耗时（Fetch/Decode/Atlas/Canvas/Total）

---

## 推荐参数（v1）

> 目标：在“典型设备”（现代 Chrome/Edge + 集成显卡/中端独显）上达到可用帧率，并提供可降级区间。

### 建议起步（demo 数据 64×64×64）

- 体素分辨率：`64×64×64`（PoC 默认）
- 步进：
  - `stepVoxels = 1.0`
  - `maxSteps = 128`
- 密度/吸收（经验值，按视觉调参）：
  - `densityMultiplier = 1.0`
  - `extinction = 1.2`

### 更高质量（128³）

- 体素分辨率：建议先从 `128×128×64` 或 `128×128×128` 开始压测
- 步进建议：
  - `stepVoxels = 1.25 ~ 2.0`
  - `maxSteps = 128`（必要时降到 96/64）

### 性能降级策略（建议）

- 当 FPS < 30（连续 2~3 次采样）：
  - 优先增大 `stepVoxels`（例如 `+0.25`）
  - 降低 `maxSteps`（例如 `128 → 96 → 64`）
  - 仍不足时：降低体素分辨率（服务端/数据侧）

---

## 性能报告（PoC 输出项）

### 指标口径

- FPS：来自 PoC 页面内的帧率采样（基于 Cesium `postRender` 帧事件）。
- 内存：
  - `JS heap`：`performance.memory`（仅 Chrome/Chromium 可用，Safari 可能为 `-`）
  - `Decoded bytes`：VOLP 文件大小（下载）作为近似输入成本
  - `Atlas canvas`：2D atlas RGBA buffer 近似占用（`width*height*4`）
- 加载耗时：
  - `Fetch`：下载耗时
  - `Decode`：VOLP 解码耗时（zstd 解压 + typed array 构建）
  - `Atlas`：3D→2D atlas 组装耗时
  - `Canvas`：将 atlas 写入 canvas（GPU 纹理源）
  - `Total`：上述总和

### Demo 数据固定成本（可复现）

- VOLP 文件：约 `114 KB`（zstd 压缩后）
- 解码后体素数据：`64³ * uint8 = 262,144 B ≈ 256 KB`
- Atlas 纹理（8×8 切片网格，512×512）：
  - RGBA canvas buffer：`512 * 512 * 4 = 1,048,576 B ≈ 1.0 MB`

### 结果记录（填写模板）

> 建议用同一份 demo 数据，在不同设备上记录该表格（推荐至少 3 档：低端/中端/高端）。

| 设备 | 浏览器 | 分辨率 | stepVoxels / maxSteps | FPS（静止/交互） | JS heap | Total 加载耗时 |
|---|---|---:|---|---:|---:|---:|
|（填写）|（填写）|（填写）| 1.0 / 128 |（填写）|（填写）|（填写）|

---

## 已知限制（PoC scope）

- 未做地形/深度遮挡：云体目前作为后处理叠加到场景上（不判断与地球/建筑相交）。
- 光照模型简化：仅做吸收/透明度混合，未做多次散射、相位函数、阴影等。
- 纹理格式为 2D atlas：便于兼容，但在更大体素分辨率下需要进一步优化（砖块/LOD/流式）。

---

## 后续建议

1. 加入深度裁剪（结合 `depthTexture` 或地球交点）避免云体穿透地表。
2. 引入 LOD/分块（bricks）与按视野流式加载，减少一次性 atlas 纹理尺寸。
3. 增加性能自适应：根据 FPS 动态调参（step/maxSteps/分辨率）。
4. 对比验证 Cesium VoxelPrimitive：在同等数据/参数下对比其性能与效果，决定是否迁移到原生体素管线。

