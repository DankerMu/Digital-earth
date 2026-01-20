# [ST-0022] 自建底图/地形数据许可与归因清单（Basemap/Terrain Licenses Checklist）

更新时间：2026-01-20

> 目的：形成可用于上线合规审计的书面清单与风险结论，覆盖 Digital Earth 项目涉及/候选的底图（影像）与地形（DEM）数据源许可、归因与免责声明要求。  
> 免责声明：本文为工程合规排查材料，不构成法律意见；对外发布（尤其商业化）前请法务复核并留档原始授权文件与当期网页/条款快照。

## 1) 项目现状核对（仓库内配置）

### 1.1 当前 Web 端已接入的影像底图

来源：`apps/web/src/config/basemaps.ts`

- `s2cloudless-2021`（EOX 公共瓦片服务，URL Template / XYZ）
- `nasa-gibs-blue-marble`（NASA GIBS，WMTS）

### 1.2 当前 Web 端地形（Terrain/DEM）

目前未在 Cesium Viewer 中配置外部 `terrainProvider`（默认椭球体，不涉及外部 DEM 数据许可问题）。  
若后续接入 **Copernicus DEM / Cesium World Terrain / 自建 DEM 切片**，需要按本文 3.4/4 重新评审。

---

## 2) 数据源汇总表（审计一页纸）

| 数据源 | 类型 | 当前是否使用 | 许可/条款类型 | 归因要求 | 允许商用 | 允许再分发 | 主要限制与风险结论 |
|---|---|---:|---|---|---|---|---|
| NASA GIBS / Blue Marble（`BlueMarble_NextGeneration`） | 影像底图（WMTS） | ✅ | NASA Images & Media Usage Guidelines（NASA 内容通常不受版权保护；第三方内容除外） | 需标注 NASA 为来源；不得暗示 NASA 背书 | **有条件允许** | **有条件允许** | 风险中低：需做“按图层核对版权来源/第三方标注”与“不背书”免责声明 |
| Sentinel-2 cloudless 2021（EOX 公共瓦片） | 影像底图（XYZ） | ✅（默认） | **CC BY-NC-SA 4.0**（非商业 + 署名 + 相同方式共享） | 需署名 EOX + 链接 + 标注“Contains modified Copernicus Sentinel data 2021” | **不允许**（除非购买/签署商业授权） | **有条件允许**（仅非商用且 SA） | 风险高：默认底图不满足商业化发布；建议仅用于 Demo/内部环境或替换为可商用方案 |
| Copernicus Sentinel-2（原始 Sentinel Data） | 影像数据（下载/自建） | ⚠️（候选/上游） | EU “Legal notice on the use of Copernicus Sentinel Data…”（free/full/open） | 必须向接收者说明来源：`Copernicus Sentinel data [Year]`；修改后用 `Contains modified…` | ✅ | ✅ | 风险低：合规关键在“归因文本必须出现 + 无担保免责声明” |
| Copernicus DEM（CopDEM GLO-30/90，WorldDEM™ 衍生） | 地形/高程（下载/自建） | ⚠️（候选） | **ESA 与用户之间的限制性许可**（Copernicus Contributing Mission Data Access Licence, 2025-02-21） | 必须展示指定版权行（含 EU/ESA） | **多数情况不允许**（普通用户仅限非商业） | **严格受限**（仅限接受条款的参与方；禁止对公众可重建式分发） | 风险高：若目标是对外/商用发布，自建地形优先选可商用 DEM 或获取额外授权 |

> 说明：表中“再分发”指将数据或其可重建形式（例如可导出/可下载的瓦片、可还原原始高程值的 Terrain tiles）提供给第三方。

---

## 3) 数据源逐项条款与归因/免责声明文本

### 3.1 Sentinel-2 cloudless 2021（EOX 公共瓦片）

**项目使用方式**

- URL Template：`https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2021_3857/default/g/{z}/{y}/{x}.jpg`
- WMTS Capabilities：`https://tiles.maps.eox.at/wmts/1.0.0/WMTSCapabilities.xml`
- Capabilities 中对应图层标识：`s2cloudless-2021_3857`

**许可类型**

来自 WMTS Capabilities 的 `ows:Abstract`（节选）表明该图层为 **CC BY-NC-SA 4.0**，并明确指出商业使用需另行授权：

> Sentinel-2 cloudless - https://s2maps.eu … (Contains modified Copernicus Sentinel data 2021) released under Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License. For commercial usage please see https://cloudless.eox.at

**归因要求（可直接复制）**

建议至少满足以下要素：来源 + 作者/提供方 + 年份 + 许可证 + 链接 + “modified Copernicus Sentinel data”声明。

- **短归因（UI 展示）**：`EOX / Sentinel-2 cloudless (2021)`
- **完整归因（弹窗/数据来源页）**：
  - `Sentinel-2 cloudless - https://s2maps.eu by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2021) — CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)`

**商用与再分发边界**

- **商用**：不允许（NC）；如需商用，需按其提示对接 `https://cloudless.eox.at` 获取商业授权/服务。
- **再分发**：仅在满足 **非商业 + 署名 + 相同方式共享（SA）** 的前提下允许；若你将其瓦片缓存并对外提供（CDN/代理/自建瓦片服务），通常构成再分发，需要按 CC BY-NC-SA 约束执行（且仍然不能商用）。

**风险结论**

- 若产品计划 **商业化对外发布**，则当前默认底图 `s2cloudless-2021` **不满足**，风险高。

---

### 3.2 NASA GIBS / Blue Marble（`BlueMarble_NextGeneration`）

**项目使用方式**

- WMTS Endpoint：`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi`
- Layer：`BlueMarble_NextGeneration`

**许可/条款要点（NASA Images and Media Usage Guidelines）**

NASA “Images and Media” 指南（`https://www.nasa.gov/nasa-brand-center/images-and-media/`）给出关键原则（节选）：

- `NASA content … generally are not subject to copyright in the United States. … You may use this material for educational or informational purposes…`
- `NASA content used in a factual manner that does not imply endorsement may be used without needing explicit permission. NASA should be acknowledged as the source of the material.`
- 同时指出 NASA 网站上可能存在 **第三方版权材料**，会以版权标注方式注明，NASA 的使用不等于向第三方转授使用权。

> 实务建议：NASA GIBS 的不同图层可能聚合多来源数据；对外发布前应按“实际启用图层”逐条核对其元数据/版权来源，避免误用第三方受限内容。

**归因要求（建议文本，可直接复制）**

- **短归因（UI 展示）**：`NASA GIBS / Blue Marble (MODIS)`
- **完整归因（弹窗/数据来源页）**：
  - `NASA GIBS (Global Imagery Browse Services) — Blue Marble (MODIS) via https://gibs.earthdata.nasa.gov/`

**商用与再分发边界（工程视角）**

- **商用**：通常可行（以“事实性使用、不暗示 NASA 背书”为前提）；但需注意图层可能含第三方版权内容，需按层核对。
- **再分发**：NASA 内容通常可再分发；若图层含第三方版权内容，则需遵守第三方权利人要求。

**建议补充免责声明（面向对外发布）**

- `NASA 不对本产品/服务提供背书或认可；相关内容为数据可视化展示。`
- `部分资料可能包含第三方版权内容，版权归原权利人所有；如有版权标注请按标注执行。`

---

### 3.3 Copernicus Sentinel-2（用于自建影像底图的上游数据）

> 说明：当前项目影像底图使用的是 EOX 已处理的 cloudless 瓦片；但若要实现“可商用可再分发”的自建影像底图，典型路径是基于 Sentinel-2 原始数据自行生产拼接/色彩校正/切片。

**许可/条款（Legal notice）**

欧盟 “Legal notice on the use of Copernicus Sentinel Data and Service Information”（PDF：`https://sentinels.copernicus.eu/documents/247904/690755/Sentinel_Data_Legal_Notice`）明确：

- Sentinel 数据与服务信息 **free / full / open access**（无明示或默示担保）。
- 允许的用途包括：`reproduction`、`distribution`、`communication to the public`、`adaptation/modification/combination` 等。
- 用户需放弃对 EU/数据提供方的损害索赔（免责声明/责任限制）。

**归因要求（可直接复制）**

- 未修改直接分发/传播：
  - `Copernicus Sentinel data [Year]`
- 修改/派生后分发/传播：
  - `Contains modified Copernicus Sentinel data [Year]`

**商用与再分发边界**

- **商用**：允许（在合法使用前提下），但需包含上述归因文本与“无担保/免责”理解。
- **再分发**：允许；对外发布时必须“告知接收者数据来源”（即上述归因文本）。

---

### 3.4 Copernicus DEM（CopDEM GLO-30/90；WorldDEM™ 衍生）

**项目状态**：候选（地形/高程数据源）

**权威条款来源**

Copernicus Data Space Ecosystem STAC 集合（例如 `cop-dem-glo-30-dged-cog` / `cop-dem-glo-90-dged-cog`）给出的授权文件：

- `https://dataspace.copernicus.eu/sites/default/files/media/files/2025-06/copernicus_contributing_mission_data_access_v2_cop_dem_licenses.pdf`
- 文件标题：`COPERNICUS CONTRIBUTING MISSION DATA ACCESS LICENCE BETWEEN ESA AND COPERNICUS USER FOR THE USE OF DATA SUBJECT TO RESTRICTIVE LICENSING TERMS`（Issue date: 21/02/2025）

**关键限制条款（节选/归纳）**

- **用户类别限制**：条款明确（节选）：
  - `Any Users not falling under 3.4.1 or 3.4.2, may only use the Primary Products or Altered Products derived from them for non-commercial activities.`
  - `Reselling data provided under this Licence is strictly prohibited.`
- **再分发限制**（节选）：仅可在项目/活动参与方且对方已接受条款的情况下再分发；对未接受条款的自然人/法人再分发被排除。
- **“可重建”风险**：条款对 Primary/Altered Products 定义中包含“mosaics、subsets of substantial size”等，工程上常见的 DEM 切片（terrain tiles、可还原高程值的瓦片/网格）通常更接近 Altered Products，需按“非商业/不可再分发”边界处理。

**归因要求（可直接复制）**

条款对可公开展示（非商业）场景要求展示指定版权行；文中出现两类常用表述：

- 通用表述（用于 VIEW/发布展示等场景，按条款原文）：
  - `includes material “© CCME (year of acquisition), provided under COPERNICUS by the European Union and ESA, all rights reserved.`  
    （若为第三方卫星数据，还需使用条款中对应的第三方版权行）
- 针对 WorldDEM™ 相关 Copernicus DEM 的表述（条款原文）：
  - `"© DLR e.V. (2014-2018) and © Airbus Defence and Space GmbH (year of production) provided under COPERNICUS by the European Union and ESA; all rights reserved"`

**要求的免责声明文本（可直接复制）**

条款针对 Copernicus WorldDEM™-90 要求在对公众分发/传播时加入以下句子（条款原文）：

- `"The organisations in charge of the Copernicus programme by law or by delegation do not incur any liability for any use of the Copernicus WorldDEM™-90".`

**商用与再分发边界（结论）**

- **商用**：对“非 3.4.1/3.4.2 类用户”明确仅限非商业活动；因此对于一般商业化产品发布，**不满足**（除非你属于条款允许的用户类别或取得额外授权）。
- **再分发**：严格受限；尤其不应向公众提供可下载/可重建的 DEM 数据或瓦片服务。

**风险结论**

- 若目标是“自建地形数据可对外商用发布”，Copernicus DEM（按上述限制性许可）为 **高风险来源**。建议优先选择明确允许商用与再分发的 DEM（或购买/签署商业授权），并保留授权链路与用户类别证明材料。

---

## 4) 风险评估与合规建议（可用于上线决策）

### 4.1 风险分级（建议）

- **高风险（阻断商用发布）**
  - EOX `Sentinel-2 cloudless`：CC BY-NC-SA（NC）→ 商用不允许。
  - Copernicus DEM（限制性许可）：普通用户仅非商业 + 再分发严格受限。
- **中低风险（可通过流程/归因控制）**
  - NASA GIBS：通常可用，但需“按启用图层核对版权来源/第三方标注”，并做好“不背书”声明。
  - Copernicus Sentinel 原始数据：free/full/open，但需强制归因与“无担保/免责”理解。

### 4.2 合规落地建议（工程与流程）

1. **对外/商用环境默认禁用高风险源**：将 `s2cloudless-2021` 标记为 `demoOnly` 或仅在非商用环境启用；商用默认底图改为可商用来源（例如 NASA GIBS 或自建 Sentinel-2 拼接）。
2. **统一归因展示**：利用现有 `/api/v1/attribution` + Web 端 AttributionBar/Modal，将“底图/地形来源”与“免责声明”常驻可见。
3. **缓存/代理即再分发评审**：如果要在后端做瓦片缓存、CDN、代理转发，视作再分发/传播，应逐源确认是否允许，以及是否需要把归因/许可证链接“透传”到最终用户界面。
4. **留档与版本化**：上线前将所有关键授权文件（PDF/网页条款）以“日期 + hash”方式归档（内部合规仓库或审计材料），避免条款变更后不可追溯。

---

## 5) 上线合规检查清单（Checklist）

- [ ] 核对生产环境启用的底图/地形数据源清单（与 `apps/web/src/config/basemaps.ts`、后端配置一致）
- [ ] 每个数据源均有：许可类型、官方链接、归因文本、免责声明文本、商用/再分发边界结论
- [ ] UI 中可见归因入口（常驻）+ 归因/免责声明内容可被用户访问（无需登录）
- [ ] 若使用第三方瓦片服务：确认其服务条款允许面向公网访问与预期流量；必要时加缓存/CDN 或签署商业服务
- [ ] 若自建瓦片（影像/地形）：确认上游数据许可允许“切片后对外发布”（特别注意是否会让用户重建原始数据）
- [ ] 发布前在合规档案中留存：条款 PDF/网页快照、下载日期、版本号、哈希值

