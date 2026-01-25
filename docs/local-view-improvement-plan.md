# 局地（Local）视角「人类视野」改进方案（分析与实现计划）

更新时间：2026-01-25

## 1. 背景与问题复述

当前在 Web 端切换到地球上某一点的 Local 视角时，用户感受到的是「巨人视角 / 无人机视角」，而不是「站在地面、以人眼高度观察」的体验，典型表现：

- 周边山脉、河流等地貌比例不符合直觉（看起来自己“很高/很大”）
- 云层与太阳在视野中的位置不符合“抬头看天空”的习惯
- 整体透视与空间尺度更像高空俯瞰而非地面第一人称

本文件在 **不做代码实现** 的前提下，对现状进行技术定位，并给出可落地的改造方案、步骤与工作量估算。

参考代码：

- `apps/web/src/features/viewer/CesiumViewer.tsx`：视角切换、Local 模式相机/环境控制
- `apps/web/src/features/layers/LocalCloudStack.ts`：局地云层（悬空平面贴图）渲染
- `apps/web/src/state/viewMode.ts`：视图模式与路由状态

---

## 2. 现状技术分析

### 2.1 Local 视角相机设置（高度 / FOV / 朝向）

#### 2.1.1 进入 Local 的触发与初始点位

`CesiumViewer.tsx` 中通过 `CTRL+点击` 或 `双击` 将屏幕点位反算为经纬度，并调用 `enterLocal({ lat, lon, heightMeters })`。

- 点位高度 `heightMeters` 来自：
  - 优先 `viewer.scene.pickPosition(position)`（依赖深度缓冲/拾取支持）
  - 否则回退 `camera.pickEllipsoid(...)`（基本只得到椭球面高度，通常为 0）
- `ViewModeRoute` 会把这个高度作为 `route.heightMeters` 保存（见 `viewMode.ts` 的 `enterLocal`）

结论：Local 视角的“地表高度”在当前实现中并不可靠，尤其在 **未启用地形** 或 `pickPosition` 不可用时会退化为 `0m`。

#### 2.1.2 Local 相机默认高度：显著偏高（“巨人/无人机”根因之一）

进入 Local 后，相机飞行目的地使用了「地表高度 + offset」策略：

- `cameraPerspectiveId === 'free'` 时：`offsetMeters = 3000`
- 其他（`forward/upward`）时：`offsetMeters = 50`
- `sceneModeId === '2d'` 时：`offsetMeters = 5000`（2D 下本身不适合“站在地面”的视角）

并且 **默认相机视角是 `free`**（见 `apps/web/src/state/cameraPerspective.ts` 的 `DEFAULT_CAMERA_PERSPECTIVE_ID: 'free'`），这会导致：

- 进入 Local 时默认相机高度约为 **离地 3000m**（再叠加地形/山地高度）
- 这与人眼高度（约 1.6–1.8m）相比高出三个数量级，直接造成比例错觉与“巨人感”

此外，`CesiumViewer.tsx` 中全局设置了：

- `screenSpaceCameraController.minimumZoomDistance = 100`（初始化 Viewer 时写死）

这意味着即便把 offset 降到几米，依然可能被控制器的最小缩放距离限制住，导致“怎么都无法贴近地面”。

#### 2.1.3 Local 相机默认朝向：`free` 时为俯视（不符合人类视野习惯）

Local 模式下的 pitch 常量：

- `LOCAL_FREE_PITCH = -45°`（俯视）
- `forward = 0°`（平视）
- `upward ≈ +75°`（仰视）

在默认 `free` 模式下，进入 Local 会以 `-45°` 俯视点位，这本质上是“空中看地面”的相机语言，而不是“站在地面看四周/看天空”。

#### 2.1.4 Local 模式 FOV 与近远裁剪面

Local 模式中存在一段“局地环境更新”，对相机 frustum 和雾效进行动态调整：

- 近远裁剪面：`localFrustumForCameraHeight(heightMeters)`
  - `near = clamp(height*0.0005, 0.2, 5)`
  - `far = clamp(height*400, 50_000, 2_000_000)`
- FOV：
  - 当 `cameraPerspectiveId !== 'free'` 时强制 `fov = 75°（vertical）`
  - `free` 则恢复 base fov（默认约 60°，取决于 Cesium 默认 frustum）

风险点：

- 若目标是 1–2m 的人眼高度，`far` 的最小值仍然是 50km，深度精度可能浪费，局部物体可能出现轻微 z-fighting（需要后续按“地面模式”专门调参）
- `75° vertical` 更像广角镜头；如果期望“更贴近人眼/相机”的效果，可考虑 `~60° vertical`（在 16:9 下约等价于 90° horizontal）

---

### 2.2 DEM（地形）是否缺失：当前默认确实缺失

`CesiumViewer.tsx` 有完整的地形切换逻辑，支持：

- `none`：`EllipsoidTerrainProvider()`（无地形）
- `ion`：`createWorldTerrainAsync()`（Cesium World Terrain）
- `selfHosted`：`CesiumTerrainProvider.fromUrl(terrainUrl)`（自建 quantized-mesh）

但这段逻辑只有在 `mapConfig` 存在时才会执行（`if (!mapConfig) return;`）。

当前仓库内 `apps/web/public/config.json` / `config.dev.json` / `config.prod.json` / `config.staging.json` 均只包含 `apiBaseUrl`，未提供 `map.*` 配置，因此：

- `mapConfig` 为 `undefined`
- Viewer 使用 Cesium 默认地形（等价于 `EllipsoidTerrainProvider`）
- 结果是 **没有真实地形（DEM）**，山脉/河谷不会以地形起伏呈现

这会带来两个直接后果：

1. **地貌比例感缺失**：看起来像贴图球体，山脉“只有颜色没有形体”，很难产生真实尺度感。
2. **地表高度不可用**：Local 进入点的 `heightMeters` 更容易退化为 0，从而影响：
   - 相机离地高度计算
   - 局地云层高度（`surfaceHeightMeters + cloudOffset`）的基准

---

### 2.3 云层渲染高度是否正确

#### 2.3.1 当前有两套“云”表现方式

1) `CloudLayer`（`apps/web/src/features/layers/CloudLayer.ts`）

- 实现方式：作为 `ImageryLayer` 贴到地球表面
- 语义：更像“云量/云图层数据覆盖”，不是“天空中的云”
- 在 Local 视角下会产生明显违和：云像是“贴在地表/山体”上

2) `LocalCloudStack`（`apps/web/src/features/layers/LocalCloudStack.ts`）

- 实现方式：在指定高度生成 `RectangleGeometry(height=...)`，贴图成半透明平面
- 高度策略：`heightMeters = surfaceHeightMeters + cloudLayerHeightOffsetMeters(layer)`
  - `tcc` 默认 4500m
  - 湿度（按气压层近似）：850→1800m，700→3200m，500→5600m，300→9000m
- 高度范围整体在 **1.8–9.0km**，符合“云层通常在 1–10km”这一粗粒度要求

#### 2.3.2 LocalCloudStack 在默认视角下不会启用（关键缺口）

在 `CesiumViewer.tsx` 中，局地云层栈的启用条件是：

- `viewModeRoute.viewModeId === 'local'`
- `cameraPerspectiveId !== 'free'`
- 且非 low mode

而默认相机视角为 `free`，因此多数用户进入 Local 时：

- **看不到** `LocalCloudStack` 的“天空云”
- 只会看到 `CloudLayer` 的“地表贴图云”

这直接解释了“云层高度不对/云在不该出现的位置”这一主观感受。

---

### 2.4 太阳位置与光照：当前缺少“与时间联动的太阳模拟”

在当前代码中未发现对以下能力的显式设置：

- `viewer.scene.globe.enableLighting`
- `viewer.scene.light` 或基于时间更新的方向光
- 将 `useTimeStore().timeKey` 写入 `viewer.clock.currentTime`

因此现状更接近：

- 太阳/光照为 Cesium 默认值（可能与真实时间、选定数据时间无关）
- 缺少“随时间变化的太阳方向/阴影”，导致地面视角下不够真实

---

## 3. 根因归纳（优先级从高到低）

1. **Local 默认相机视角 = `free` → 默认离地约 3000m 且俯视 -45°**  
   进入 Local 的第一印象就是高空俯瞰，自然是“巨人/无人机”体验。

2. **全局最小缩放距离 `minimumZoomDistance = 100m`**  
   即便后续尝试将相机放到 1–2m，也可能被控制器限制而失败。

3. **默认未启用地形（DEM 缺失）**  
   地貌没有真实起伏，且地表高度基准不可靠，进一步破坏尺度感。

4. **LocalCloudStack 默认不启用（free 模式下）+ CloudLayer 仍贴地显示**  
   云在 Local 视角下更像“贴在地表的云图”，与人类视野习惯冲突。

5. **缺少与时间联动的太阳/光照**  
   “抬头看太阳”的体验不真实，缺少阴影与方向感。

---

## 4. 技术方案（目标、策略与关键设计）

### 4.1 目标定义（建议作为验收标准）

Local（地面）视角满足以下“人类尺度”目标：

- 相机高度：默认 **眼高约 1.7m**（可配置范围 1.2–2.0m）
- 视角：默认 **平视或轻微俯视（-5° ~ 0°）**，支持自由抬头/低头
- FOV：默认 **~60° vertical**（或提供 55–75° 可调）
- 地形：Local 下能看到真实地形起伏（至少 World Terrain 级别）
- 云：Local 下云应出现在天空（高度约 1–10km），并可关闭“贴地云图”
- 太阳：与时间联动，能体现方向与阴影（可按性能开关）

---

### 4.2 相机方案：引入“人类尺度地面模式（Human Ground Mode）”

核心思想：Local 的默认行为不应是“飞到点上方俯瞰”，而应是“落地到点位附近，以人眼高度站立并观察”。

建议方案（二选一，推荐 A）：

#### A) 新增 Local 专用的相机预设：`human`

- 新增 `CameraPerspectiveId = 'human'`（或在 Local 内部新增一个模式，不一定暴露为全局 store）
- 进入 Local 默认切换到 `human`
- `human` 的控制语义：
  - 默认平视（pitch ~ 0）
  - 禁用 orbit rotate，启用 look（类似当前 forward/upward 的控制）
  - 允许更低的 `minimumZoomDistance`（例如 0.5–2m）

优点：与现有的 `forward/upward/free` 清晰区分，不破坏 `free` 在全局模式的使用习惯。

#### B) 保持 `free` 但“在 Local 内部重定义 free 的默认高度/朝向”

- `free` 在 Local 中默认高度改为 2–20m（而不是 3000m）
- 默认 pitch 改为 0（而不是 -45°）
- 并允许用户自由旋转/俯仰

优点：改动少。缺点：`free` 在全局/局地语义不同，容易让用户理解混乱。

#### 人类尺度落地算法（两段式，避免地形未加载）

由于地形加载存在异步/LOD 的问题，建议采用“两段式落地”：

1) **快速到达安全高度**：先飞到 `groundApprox + safeOffset`（例如 200–500m）  
   目的：确保地形瓦片加载到足够精度，避免直接落地时出现穿地/抖动。

2) **采样真实地表高度**：使用 terrain provider 采样目标点 `lon/lat` 的高程  
   - 首选：`sampleTerrainMostDetailed(viewer.terrainProvider, [Cartographic.fromDegrees(lon, lat)])`
   - 回退：`viewer.scene.globe.getHeight(cartographic)`（只对已加载瓦片有效）
   - 若 terrain provider 为 `EllipsoidTerrainProvider`，则高度视为 0，并给出 UI 提示“无地形模式”

3) **落地到 eye height**：`destinationHeight = groundHeight + eyeHeight`（eyeHeight 默认 1.7m）

4) **同步更新 Local route.heightMeters**：把采样得到的 groundHeight 写回 Local route（用于云层高度基准与信息面板显示）

#### Frustum/雾效建议调整

现有 `localFrustumForCameraHeight` 对 “2m 高度” 的参数并非为地面模式设计。建议在 `human` 模式下单独策略：

- `near`：0.05–0.2m（避免近处裁剪；仍需兼顾深度精度）
- `far`：10–50km（足够覆盖地平线与远山，避免过大 far 造成深度浪费）
- 雾效：从“高度驱动”改为“地面模式固定/弱雾”，避免近地出现过浓的全局雾

---

### 4.3 DEM/地形方案：Local 必须启用 Terrain Provider

当前默认 `config.json` 未配置 `map.terrainProvider`，导致 DEM 缺失。建议：

- 在运行时配置中启用地形：
  - 方案 1：`terrainProvider: 'ion'` + `cesiumIonAccessToken`
  - 方案 2：`terrainProvider: 'selfHosted'` + `selfHosted.terrainUrl`（quantized-mesh）
- 对 Local 模式做强依赖处理：
  - 若 terrain 不可用：给出 UI notice（例如“无地形模式，地面视角精度受限”）
  - 可选：Local 入口处提示用户切换到有地形环境，或自动降级为“俯瞰模式”（避免穿地）

精度建议：

- 最低：World Terrain 或同等级别（满足宏观山脉/河谷）
- 若要“站在地面”的真实感，后续可考虑叠加：
  - 3D Tiles 城市/建筑（已存在 OSM Buildings 开关）
  - 更高分辨率 DEM（取决于数据与成本）

---

### 4.4 云层方案：Local 视角统一使用“天空云”，避免贴地云误导

建议调整 Local 云层显示策略：

- 当进入 Local 且开启云图层时：
  - 默认启用 `LocalCloudStack`（包括 `free/human`，不应因默认 `free` 而禁用）
  - 同时对同一云图层的 `CloudLayer(ImageryLayer)` 做降级：
    - Local 模式默认隐藏（避免“贴地云”造成高度错觉）
    - 或提供 UI 选项：“云显示：贴地图层 / 天空云层 / 两者叠加”

高度策略：

- 保留 `LocalCloudStack` 的 1–10km 档位（当前实现符合）
- 将 `surfaceHeightMeters` 的来源从“点击拾取高度”升级为“地形采样高度”，避免在山地出现云层过低

范围策略（可选优化）：

- 目前 `LOCAL_CLOUD_TILE_ZOOM = 6` 且 `RADIUS = 1`，覆盖范围很大，可能：
  - 从地面看不到边界（优点）
  - 但贴图分辨率偏低、平面感强（缺点）
- 可按相机高度动态选择 zoom/radius：
  - 地面模式：提高 zoom（例如 8–10），radius 小（1–2），保证云纹理细节
  - 高空模式：降低 zoom，radius 大，保证覆盖不露边

---

### 4.5 太阳与光照方案：与 timeKey 联动 + 可控性能开关

建议在 Local 模式提供“真实太阳/光照”能力：

- 将 `useTimeStore().timeKey` 同步到 Cesium：
  - `viewer.clock.currentTime = JulianDate.fromIso8601(timeKey)`
  - 视产品定义决定 `clock.shouldAnimate`（静态时刻 vs 播放）
- 启用地表光照：
  - `viewer.scene.globe.enableLighting = true`
  - 可选：为 OSM Buildings 开启阴影（注意性能）
- UI 开关：
  - “真实光照（性能开销）”开关
  - 在 low mode 自动关闭

---

## 5. 实现步骤（建议拆分为可验收的任务）

> 说明：以下为实现计划清单，不在本次输出中直接改代码。

### Step 0：定义验收用例与参数（0.5d）

- 确认 Local 视角的产品定义：
  - 默认是否必须是“落地人眼”
  - 是否保留“俯瞰/无人机”模式作为可选
- 明确默认参数：
  - eyeHeight（1.7m）
  - vertical FOV（60° 或 75°）
  - default pitch（0° 或 -5°）

### Step 1：补齐 DEM（地形）配置与运行时开关（0.5–1d）

- 在部署环境的 `config.json` 增加 `map.terrainProvider`（ion 或 selfHosted）
- 增加“地形缺失”的用户提示与降级策略（避免穿地/尺度错觉）

### Step 2：实现 Human Ground Mode（1–2d）

- 引入 Local 默认的“人类尺度”相机模式（方案 A 推荐）
- 调整 Local 进入逻辑：
  - 两段式飞行 + 地形采样 + 落地
  - 将采样高度回写到 Local route（用于面板与云层）
- 调整控制器限制：
  - Local 模式下将 `minimumZoomDistance` 降至 0.5–2m
  - 退出 Local 后恢复全局设置
- 为地面模式单独调整 frustum 与雾效参数

### Step 3：Local 云层显示策略调整（0.5–1d）

- Local 默认启用 `LocalCloudStack`（不受 `free` 限制）
- Local 下默认隐藏 `CloudLayer`（或提供“贴地/天空”切换）
- 使用地形采样高度作为 `surfaceHeightMeters`
- 可选：按相机高度动态调整 LocalCloudStack 的 zoom/radius

### Step 4：太阳/光照联动（0.5–1d）

- timeKey → `viewer.clock.currentTime` 同步
- 开启 `globe.enableLighting`（Local 或全局可配）
- low mode 下自动关闭，避免性能回退

### Step 5：验证与回归（0.5–1d）

- 典型地形点位（平原/山地/海岸）验证：
  - 默认进入 Local 是否为“落地人眼”
  - 地平线距离、地物比例是否自然
  - 云是否在天空、太阳方向是否合理
- 性能验证：
  - low/high mode 下帧率
  - OSM Buildings + lighting + cloud stack 的组合开销

---

## 6. 工作量估算（人日）

| 模块 | 主要工作 | 估算 |
|---|---|---:|
| 需求对齐 | 验收标准、默认参数、交互定义 | 0.5d |
| 地形接入 | 配置/降级提示/验证 | 0.5–1d |
| 人眼相机 | 两段式落地、地形采样、控制器/裁剪面/雾效调参 | 1–2d |
| 局地云 | 启用策略、贴地云降级、基于地形高度 | 0.5–1d |
| 太阳光照 | timeKey 联动、lighting 开关、性能策略 | 0.5–1d |
| 测试回归 | 点位用例+性能回归 | 0.5–1d |
| **合计** |  | **3.5–6.5d** |

---

## 7. 风险与注意事项

- **地形未加载导致穿地/抖动**：必须做“两段式落地”或等待地形采样完成再落地。
- **minimumZoomDistance 与地面模式冲突**：需要在 Local 内动态调整并在退出时恢复。
- **深度精度与 z-fighting**：far 过大/near 过小会导致地面与云层/建筑的深度问题，需要针对地面模式重新调参。
- **云层平面感**：`LocalCloudStack` 是“贴图平面”，从地面看可能有边缘/平面感，可通过扩大覆盖、提高分辨率、曲面化或未来引入体积云改进。
- **光照性能开销**：enableLighting + 阴影在低端设备可能明显掉帧，需做开关与自动降级。

---

## 8. 建议的最小可行版本（MVP）

若希望最快消除“巨人视角”主观问题，建议优先实现：

1) Local 默认切换到地面模式（eyeHeight≈1.7m、pitch≈0°），并降低 `minimumZoomDistance`  
2) 启用 DEM（至少 World Terrain）  
3) Local 默认启用 `LocalCloudStack` 并隐藏贴地 `CloudLayer`

完成以上三点后，山脉/河流尺度、云层位置会同步显著改善；太阳/光照可作为第二阶段增强项。

