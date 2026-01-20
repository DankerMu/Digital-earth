# [ST-0023] DEM -> 地形瓦片生产 PoC（Copernicus DEM -> quantized-mesh）

## 1. Overview

目标：验证 **自建 DEM（Copernicus DEM）** 可被 **CesiumJS / Cesium for Unreal** 端以 **quantized-mesh-1.0** 地形瓦片格式加载。

本 PoC 聚焦可行性与端到端链路：

- 选取一个约 `1° x 1°` 的样区（北京周边）
- 下载 Copernicus DEM GeoTIFF
- 生成 `EPSG:4326 + tms` 的 quantized-mesh 地形瓦片金字塔（LOD）
- 产出 `layer.json` + `{z}/{x}/{y}.terrain`
- 给出对象存储部署与 CesiumJS 加载示例
- 提供粗略成本估算与下一步建议

## 2. Data Source & License Notes（依赖 ST-0022）

数据源：Copernicus DEM（GLO-30 Public / GLO-90），AWS Open Data：

- https://registry.opendata.aws/copernicus-dem/

许可与合规要点请先阅读并遵循：

- `docs/st-0022-basemap-terrain-licenses.md`（重点：3.4 Copernicus DEM）

**重要：本 PoC 按“非商业/内部验证”使用。**

- Copernicus DEM 对普通用户通常仅允许非商业用途
- 对公众提供可下载/可重建的 DEM/terrain tiles 可能构成再分发风险

## 3. Sample Region（Beijing）

推荐样区（约 `1° x 1°`，与 Copernicus DEM 1° 切片对齐）：

- West/South/East/North = `116.0, 39.0, 117.0, 40.0`

> 备注：对齐 1° 可以避免 PoC 阶段引入多 tile mosaic 的额外复杂度。

## 4. Implementation（Repo）

代码位置（均在 `services/data-pipeline/`）：

- 核心模块：`services/data-pipeline/src/terrain/`
  - `dem_downloader.py`：通过 Copernicus STAC 获取 elevation GeoTIFF 下载链接并缓存
  - `tile_pyramid.py`：Cesium quantized-mesh（EPSG:4326 + TMS）瓦片坐标与范围计算
  - `mesh_generator.py`：生成 `quantized-mesh-1.0`（规则网格 + 高水位索引编码）
- 端到端脚本：`services/data-pipeline/scripts/poc_terrain_pipeline.py`

### 4.1 Output Layout

脚本输出一个可直接部署的 terrain tileset 目录：

- `layer.json`
- `{z}/{x}/{y}.terrain`（binary）

其中 `layer.json` 使用：

- `format = quantized-mesh-1.0`
- `scheme = tms`
- `projection = EPSG:4326`
- `available` 仅覆盖样区相关瓦片范围，避免客户端请求全球瓦片

## 5. Runbook（生成瓦片）

在 `services/data-pipeline/` 目录下运行（建议先使用 `--dry-run` 看瓦片数量）：

```bash
python scripts/poc_terrain_pipeline.py \
  --dataset glo30 \
  --bbox 116 39 117 40 \
  --min-zoom 0 \
  --max-zoom 12 \
  --grid-size 65 \
  --out-dir /tmp/terrain-poc \
  --dry-run
```

正式生成（默认输出**非 gzip** payload，便于直接静态托管验证）：

```bash
python scripts/poc_terrain_pipeline.py \
  --dataset glo30 \
  --bbox 116 39 117 40 \
  --min-zoom 0 \
  --max-zoom 12 \
  --grid-size 65 \
  --out-dir /tmp/terrain-poc
```

可选：输出 gzip payload（用于对象存储/CDN 成本优化；需要正确设置 `Content-Encoding: gzip`）：

```bash
python scripts/poc_terrain_pipeline.py \
  --dataset glo30 \
  --bbox 116 39 117 40 \
  --min-zoom 0 \
  --max-zoom 12 \
  --grid-size 65 \
  --gzip \
  --out-dir /tmp/terrain-poc
```

## 6. Deployment（对象存储 + CORS）

### 6.1 S3（示例）

上传 `layer.json` 与瓦片目录：

```bash
aws s3 sync /tmp/terrain-poc s3://YOUR_BUCKET/terrain/beijing/ --acl public-read
```

若启用 `--gzip` 输出，需要为 `.terrain` 设置：

- `Content-Encoding: gzip`
- `Content-Type: application/vnd.quantized-mesh`（或 `application/octet-stream`）

建议启用 CORS（示例）：

```json
[
  {
    "AllowedHeaders": ["*"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedOrigins": ["*"],
    "ExposeHeaders": ["ETag"]
  }
]
```

## 7. CesiumJS Loading（验证）

在 CesiumJS 中加载：

```js
const terrainProvider = await Cesium.CesiumTerrainProvider.fromUrl(
  "https://YOUR_DOMAIN/terrain/beijing/"
);

const viewer = new Cesium.Viewer("cesiumContainer", {
  terrainProvider,
});

viewer.camera.flyTo({
  destination: Cesium.Cartesian3.fromDegrees(116.4, 39.9, 15000),
});
```

验证点：

- 样区地形起伏可见（相对椭球体）
- LOD 切换无明显裂缝/闪烁（PoC 为规则网格，极端情况下可能出现接缝，可通过 skirt/改进采样降低）
- 网络请求仅发生在 `available` 指定的瓦片范围内

## 7.1 Cesium for Unreal Loading（验证）

Cesium for Unreal 的 `ACesium3DTileset` 支持旧的 `layer.json / quantized-mesh` 格式（官方文档说明见 Cesium for Unreal ref-doc）。

建议最小验证步骤：

1. 在 UE 场景中添加 `CesiumGeoreference`
2. 添加一个 `Cesium3DTileset`（Actor：`ACesium3DTileset`）
3. 将 Tileset 的 `Url` 指向你的 `layer.json`（示例：`https://YOUR_DOMAIN/terrain/beijing/layer.json`）
4. 将相机/玩家移动到北京区域（约 `116.4E, 39.9N`）观察地形起伏与 LOD

> 提示：当 tileset 使用 `layer.json / quantized-mesh` 而不是 3D Tiles 时，`MaximumScreenSpaceError` 等 LOD 参数的解释可能与 3D Tiles 有比例差异（见 Cesium for Unreal 文档说明）。PoC 阶段优先观察“能加载 + LOD 切换合理 + 性能可接受”。

## 8. Performance Notes（PoC）

该 PoC 使用“规则网格”生成 quantized-mesh：

- `grid-size=65`：每 tile 顶点约 `65*65=4225`
- 三角面约 `2*(64*64)=8192`

这不是生产级最优（生产通常会做 mesh simplification、skirt、法线/水体 mask 等扩展），但足以验证链路与兼容性。

建议在 PoC 验证时记录：

- 生成时间（脚本输出 `elapsed_s`）
- 产物大小（脚本输出 `total_bytes`）
- Cesium 端加载时网络面数、帧率（浏览器 devtools / UE profiler）

## 9. Cost Estimation（粗略）

以下为量级估算（实际以脚本输出为准）：

### 9.1 Sample Region（1°x1°）

以 `max_zoom=12` 为例，1° 区域在 z=12 的瓦片数约为：

- tile size ≈ `180 / 2^12 ≈ 0.04395°`
- 1° 覆盖约 `23 x 23 ≈ 529` tiles（最高层）
- 加上 0..12 各层总数通常 `< 700` tiles

单 tile 大小：

- 非 gzip：通常 `~70KB` 级别（规则网格 + 索引）
- gzip：视数据起伏与编码分布，通常能显著下降

因此样区产物量级：

- 非 gzip：`~50MB` 级别
- gzip：`~10–30MB` 级别（粗略）

### 9.2 China / Global（外推建议）

外推时建议按“瓦片数量”估算：

- China 约 `~960万 km²`，1°x1° 在 40°N 附近约 `~(85km x 111km)`，粗略折算需要几百到上千个 1° tile（取决于覆盖定义）
- 生产时将采用更合理的 max zoom 与 mesh simplification，成本会显著不同

**存储成本**（S3 Standard）：

- 以 `X GB` 产物计，月成本约 `X * $0.023 / GB-month`（以 AWS us-east-1 为例；以实际区域定价为准）

**出网成本**：

- 取决于访问量与 CDN；terrain tiles 属于高频小文件，建议配 CDN + 合理 cache-control

## 10. Next Steps（Production）

- 增加 skirt 生成（减少 LOD 裂缝）
- 引入 mesh simplification（减少顶点与文件大小）
- 研究并实现扩展：vertex normals / watermask / metadata（按 UE/Web 需求）
- 若目标为对外/商用发布：重新评估 DEM 数据源与授权路径（Copernicus DEM 存在再分发/商用限制）
