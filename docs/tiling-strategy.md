# 瓦片坐标系与 Zoom 策略（EPSG:4326 + zoom 上限）

本文档用于统一 Digital Earth 的瓦片坐标系（CRS）与 zoom 策略，避免数据生产端、API、客户端在瓦片索引与 zoom 上产生歧义，并通过 zoom 上限控制计算与存储成本。

## 1. 坐标系（CRS）

- 统一采用 `EPSG:4326`（WGS84 Geographic，单位为度）。
- 坐标轴约定采用常见的 GIS/XYZ 约定：`x=lon(经度)`、`y=lat(纬度)`。
- 该约定用于瓦片索引与范围裁剪；如渲染端需要 WebMercator 等其他投影，可在客户端侧进行转换。

## 2. Zoom 分层策略

### 2.1 Global（全局瓦片）

- zoom 范围：`0–6`
- 用途：全球范围概览层（低分辨率、低成本）。
- 目标：控制瓦片数量与存储体量，避免生成全球高 zoom 瓦片。

### 2.2 Event（事件区域瓦片）

- zoom 范围：`8–10`
- 用途：台风、暴雨、灾害等事件关注区域的高分辨率展示。
- 目标：仅在事件区域提升细节，不对全球范围扩展到高 zoom。
- 说明：`zoom=7` 当前预留（不生成），可作为未来扩展或过渡层。

## 3. Tile Size

- 固定为 `256×256` 像素。

## 4. 配置与加载

- 配置文件：`config/tiling.yaml`
- Data Pipeline 加载入口：`services/data-pipeline/src/tiling/config.py`
  - `load_tiling_config()`：从 YAML 解析并校验配置
  - `get_tiling_config()`：带缓存的读取（依据文件 mtime/size 变化自动失效）
- 可选环境变量：`DIGITAL_EARTH_TILING_CONFIG` 可指定配置文件路径，便于本地/环境差异化部署。

## 5. 变更原则

- CRS 变更属于破坏性变更：需要同步瓦片路径规范、数据生产端与客户端坐标转换逻辑，并评估存量瓦片迁移成本。
- zoom 上限调整需要评估：瓦片数量增长、计算耗时、存储与带宽成本，并在 CI/CD 或离线任务中验证。
