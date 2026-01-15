# 数字地球气象可视化平台 - UI/UX 设计规范

> 版本: v1.0 | 更新日期: 2026-01-14

## 一、设计概述

### 1.1 设计理念

本平台采用 **Dark Mode + Glassmorphism** 设计风格，营造专业、沉浸式的气象数据可视化体验。

**核心原则**：
- **数据优先**：UI 服务于数据展示，不喧宾夺主
- **沉浸体验**：深色背景突出地球和气象可视化效果
- **一致性**：Web 与 UE 端保持视觉语言统一
- **可访问性**：确保对比度和可读性

### 1.2 适用范围

| 平台 | 技术栈 | 适用场景 |
|------|--------|----------|
| Web | CesiumJS + TypeScript + Tailwind | 点位仰视、区域事件模式 |
| UE | UMG + Slate | 飞行模拟、沉浸式特效 |

---

## 二、设计系统

### 2.1 色彩体系

#### 主色板 (Dark Mode)

```css
:root {
  /* 主色 - 科技蓝 */
  --color-primary: #3B82F6;        /* Blue-500 */
  --color-primary-hover: #2563EB;  /* Blue-600 */
  --color-primary-light: #60A5FA;  /* Blue-400 */

  /* 背景色 */
  --color-bg-base: #0F172A;        /* Slate-900 */
  --color-bg-elevated: #1E293B;    /* Slate-800 */
  --color-bg-glass: rgba(30, 41, 59, 0.8); /* Glassmorphism */

  /* 文字色 */
  --color-text-primary: #F8FAFC;   /* Slate-50 */
  --color-text-secondary: #94A3B8; /* Slate-400 */
  --color-text-muted: #64748B;     /* Slate-500 */

  /* 边框色 */
  --color-border: rgba(148, 163, 184, 0.2); /* Slate-400/20 */
  --color-border-hover: rgba(148, 163, 184, 0.4);

  /* 功能色 */
  --color-success: #22C55E;        /* Green-500 */
  --color-warning: #F59E0B;        /* Amber-500 */
  --color-error: #EF4444;          /* Red-500 */
  --color-info: #06B6D4;           /* Cyan-500 */
}
```

#### 气象数据色标（默认调色板）

色标渲染规则：默认使用本节调色板；若图层提供 `legend.json`，则以 `legend.json` 为准并动态渲染图例（详见 6.5）。

```css
/* 温度色标 (冷→热) */
--temp-cold: #3B82F6;    /* -20°C 以下 */
--temp-cool: #06B6D4;    /* -20°C ~ 0°C */
--temp-mild: #22C55E;    /* 0°C ~ 20°C */
--temp-warm: #F59E0B;    /* 20°C ~ 35°C */
--temp-hot: #EF4444;     /* 35°C 以上 */

/* 降水色标 */
--precip-light: #93C5FD;  /* 小雨 0-10mm */
--precip-moderate: #3B82F6; /* 中雨 10-25mm */
--precip-heavy: #1D4ED8;  /* 大雨 25-50mm */
--precip-storm: #7C3AED;  /* 暴雨 50mm+ */

/* 风险等级 */
--risk-low: #22C55E;
--risk-medium: #F59E0B;
--risk-high: #EF4444;
--risk-extreme: #DC2626;
```

### 2.2 字体系统

#### 字体家族

```css
/* 数据展示 - 等宽字体 */
--font-mono: 'Fira Code', 'JetBrains Mono', monospace;

/* UI 文字 - 无衬线 */
--font-sans: 'Inter', 'Noto Sans SC', system-ui, sans-serif;

/* 标题 - 几何无衬线 */
--font-display: 'Space Grotesk', 'Inter', sans-serif;
```

#### Google Fonts 导入

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fira+Code:wght@400;500;600&family=Inter:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
```

#### 字号规范

| 用途 | 字号 | 字重 | 行高 |
|------|------|------|------|
| H1 标题 | 32px | 700 | 1.2 |
| H2 标题 | 24px | 600 | 1.3 |
| H3 标题 | 20px | 600 | 1.4 |
| 正文 | 14px | 400 | 1.5 |
| 数据值 | 16px | 500 | 1.2 |
| 标签 | 12px | 500 | 1.4 |
| 辅助文字 | 12px | 400 | 1.5 |

### 2.3 间距系统

基于 4px 网格：

```css
--space-1: 4px;
--space-2: 8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
--space-10: 40px;
--space-12: 48px;
--space-16: 64px;
```

### 2.4 圆角规范

```css
--radius-sm: 4px;   /* 小按钮、标签 */
--radius-md: 8px;   /* 卡片、输入框 */
--radius-lg: 12px;  /* 面板、模态框 */
--radius-xl: 16px;  /* 大型容器 */
--radius-full: 9999px; /* 圆形 */
```

### 2.5 阴影系统

```css
/* Glassmorphism 阴影 */
--shadow-glass: 0 8px 32px rgba(0, 0, 0, 0.3);
--shadow-glass-hover: 0 12px 40px rgba(0, 0, 0, 0.4);

/* 标准阴影 */
--shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3);
--shadow-md: 0 4px 6px rgba(0, 0, 0, 0.3);
--shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.3);
```

---

## 三、Glassmorphism 组件规范

### 3.1 Glass Panel 基础样式

```css
.glass-panel {
  background: rgba(30, 41, 59, 0.8);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.glass-panel:hover {
  border-color: rgba(148, 163, 184, 0.4);
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
}
```

### 3.2 Tailwind CSS 实现

```html
<!-- Glass Panel -->
<div class="bg-slate-800/80 backdrop-blur-xl border border-slate-400/20
            rounded-xl shadow-lg hover:border-slate-400/40
            transition-all duration-200">
  <!-- Content -->
</div>

<!-- Glass Button -->
<button class="bg-blue-500/90 backdrop-blur-sm text-white px-4 py-2
               rounded-lg hover:bg-blue-600 transition-colors
               cursor-pointer">
  Button
</button>
```

---

## 四、Web 客户端布局

### 4.1 整体布局结构

```
┌─────────────────────────────────────────────────────────────┐
│  [Logo]  场景切换                               [设置] [用户] │  ← 顶部导航栏
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                                                             │
│                      Cesium 地球视图                         │
│                      (全屏背景)                              │
│                                                             │
│  ┌──────────┐                              ┌──────────────┐ │
│  │ 图层面板 │                              │   信息面板   │ │
│  │ (左侧)   │                              │   (右侧)     │ │
│  └──────────┘                              └──────────────┘ │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  ◀ ▶ ⏸  |  2024-01-15 12:00 UTC  |  ═══════●═══════  |  ⏩ │  ← 底部时间轴播放条
└─────────────────────────────────────────────────────────────┘
```

### 4.2 响应式断点

```css
/* Tailwind 断点 */
sm: 640px   /* 移动端横屏 */
md: 768px   /* 平板 */
lg: 1024px  /* 小桌面 */
xl: 1280px  /* 标准桌面 */
2xl: 1536px /* 大屏 */
```

### 4.3 布局规范

| 区域 | 宽度 | 位置 | 行为 |
|------|------|------|------|
| 顶部导航 | 100% | fixed top | 始终可见，高度 56px |
| 左侧面板 | 320px | fixed left | 可折叠，最小 48px |
| 右侧面板 | 360px | fixed right | 可折叠，按需显示 |
| 底部时间轴播放条 | 100% | fixed bottom | 始终可见，高度 64px |
| 固定归因区 | auto | fixed bottom | 始终可见，位于右下安全区（默认在时间轴上方，需与右侧面板/图例避让） |
| 地球视图 | 100% | 全屏 | z-index: 0 |

---

## 五、核心组件规范

### 5.1 顶部导航栏 (TopNavBar)

**设计要点**：
- 浮动式设计，距顶部 16px
- Glassmorphism 背景
- 高度 56px，内边距 16px

```html
<nav class="fixed top-4 left-4 right-4 h-14 z-50
            bg-slate-800/80 backdrop-blur-xl
            border border-slate-400/20 rounded-xl
            flex items-center justify-between px-4">
  <!-- Logo -->
  <div class="flex items-center gap-3">
    <svg class="w-8 h-8 text-blue-500"><!-- Globe Icon --></svg>
    <span class="font-display font-semibold text-white">Digital Earth</span>
  </div>

  <!-- 场景切换 -->
  <div class="flex items-center gap-2">
    <button class="px-3 py-1.5 rounded-lg bg-blue-500/20 text-blue-400
                   border border-blue-500/30 text-sm font-medium">
      点位仰视
    </button>
    <button class="px-3 py-1.5 rounded-lg text-slate-400
                   hover:bg-slate-700/50 text-sm cursor-pointer">
      区域事件
    </button>
  </div>

  <!-- 右侧工具 -->
  <div class="flex items-center gap-2">
    <button class="p-2 rounded-lg hover:bg-slate-700/50 cursor-pointer">
      <svg class="w-5 h-5 text-slate-400"><!-- Settings --></svg>
    </button>
  </div>
</nav>
```

### 5.2 图层控制面板 (LayerPanel)

**设计要点**：
- 左侧固定，可折叠
- 分组展示图层
- 支持拖拽排序

```html
<aside class="fixed left-4 top-24 bottom-24 w-80 z-40
              bg-slate-800/80 backdrop-blur-xl
              border border-slate-400/20 rounded-xl
              flex flex-col overflow-hidden">
  <!-- 面板头部 -->
  <div class="flex items-center justify-between p-4 border-b border-slate-700">
    <h2 class="font-semibold text-white">图层控制</h2>
    <button class="p-1 hover:bg-slate-700 rounded cursor-pointer">
      <svg class="w-4 h-4 text-slate-400"><!-- Collapse --></svg>
    </button>
  </div>

  <!-- 图层列表 -->
  <div class="flex-1 overflow-y-auto p-4 space-y-3">
    <!-- 图层组 -->
    <div class="space-y-2">
      <h3 class="text-xs font-medium text-slate-500 uppercase tracking-wider">
        气象数据
      </h3>
      <!-- 图层项 -->
      <div class="flex items-center gap-3 p-2 rounded-lg
                  hover:bg-slate-700/50 cursor-pointer group">
        <input type="checkbox" checked
               class="w-4 h-4 rounded border-slate-500 text-blue-500
                      focus:ring-blue-500 focus:ring-offset-slate-800">
        <span class="flex-1 text-sm text-slate-300">温度场</span>
        <input type="range" min="0" max="100" value="80"
               class="w-16 h-1 opacity-0 group-hover:opacity-100
                      transition-opacity">
      </div>
    </div>
  </div>
</aside>
```

### 5.3 底部时间轴播放条 (TimelineBar)

**设计要点**：
- 底部固定，浮动式（本项目“时间轴”统一指此底部播放条）
- 播放控制 + 时间显示 + 进度条
- 支持拖拽和点击跳转

```html
<div class="fixed bottom-4 left-4 right-4 h-16 z-50
            bg-slate-800/80 backdrop-blur-xl
            border border-slate-400/20 rounded-xl
            flex items-center gap-4 px-4">
  <!-- 播放控制 -->
  <div class="flex items-center gap-1">
    <button class="p-2 hover:bg-slate-700 rounded-lg cursor-pointer">
      <svg class="w-5 h-5 text-slate-400"><!-- Step Back --></svg>
    </button>
    <button class="p-2 bg-blue-500 hover:bg-blue-600 rounded-lg cursor-pointer">
      <svg class="w-5 h-5 text-white"><!-- Play/Pause --></svg>
    </button>
    <button class="p-2 hover:bg-slate-700 rounded-lg cursor-pointer">
      <svg class="w-5 h-5 text-slate-400"><!-- Step Forward --></svg>
    </button>
  </div>

  <!-- 当前时间 -->
  <div class="text-center min-w-[180px]">
    <div class="font-mono text-lg text-white">2024-01-15 12:00</div>
    <div class="text-xs text-slate-500">UTC+8</div>
  </div>

  <!-- 进度条 -->
  <div class="flex-1 relative h-2 bg-slate-700 rounded-full cursor-pointer">
    <div class="absolute left-0 top-0 h-full w-1/3 bg-blue-500 rounded-full"></div>
    <div class="absolute top-1/2 -translate-y-1/2 left-1/3 w-4 h-4
                bg-white rounded-full shadow-lg cursor-grab"></div>
  </div>

  <!-- 速度控制 -->
  <select class="bg-slate-700 text-slate-300 text-sm rounded-lg px-2 py-1
                 border border-slate-600 cursor-pointer">
    <option>1x</option>
    <option>2x</option>
    <option>4x</option>
  </select>
</div>
```

### 5.4 信息面板 (InfoPanel)

**设计要点**：
- 右侧固定，按需显示
- 展示点位/区域详细信息
- 支持多 Tab 切换

```html
<aside class="fixed right-4 top-24 bottom-24 w-[360px] z-40
              bg-slate-800/80 backdrop-blur-xl
              border border-slate-400/20 rounded-xl
              flex flex-col overflow-hidden">
  <!-- 面板头部 -->
  <div class="p-4 border-b border-slate-700">
    <div class="flex items-center justify-between">
      <h2 class="font-semibold text-white">北京市朝阳区</h2>
      <button class="p-1 hover:bg-slate-700 rounded cursor-pointer">
        <svg class="w-4 h-4 text-slate-400"><!-- Close --></svg>
      </button>
    </div>
    <p class="text-sm text-slate-500 mt-1">116.4074°E, 39.9042°N</p>
  </div>

  <!-- Tab 切换 -->
  <div class="flex border-b border-slate-700">
    <button class="flex-1 py-2 text-sm text-blue-400 border-b-2
                   border-blue-500 cursor-pointer">当前</button>
    <button class="flex-1 py-2 text-sm text-slate-400
                   hover:text-slate-300 cursor-pointer">预报</button>
    <button class="flex-1 py-2 text-sm text-slate-400
                   hover:text-slate-300 cursor-pointer">历史</button>
  </div>

  <!-- 内容区 -->
  <div class="flex-1 overflow-y-auto p-4 space-y-4">
    <!-- 数据卡片将在下一节定义 -->
  </div>
</aside>
```

### 5.5 固定归因区与数据来源入口 (AttributionBar)

**设计要点**：
- 始终可见，位于右下安全区；默认位于底部时间轴播放条上方
- 内容必须包含：底图/引擎归因、气象数据归因、`数据来源` 入口、`免责声明` 入口
- 文字支持单行省略（hover/点击可展开），入口可点击并具备可访问性（可聚焦、aria-label）
- 与右侧信息面板/图例自动避让：避免遮挡主要内容（可向左偏移或吸附到面板底部）

**数据来源入口规范**：
- 点击 `数据来源` 打开弹窗/抽屉，展示数据集清单（名称、提供方、更新时间、许可/使用限制、参考链接）
- 弹窗需支持复制引用信息（用于报告/论文/截图说明）

**免责声明规范**：
- 点击 `免责声明` 展示免责声明内容（弹窗/气泡均可），默认文案需覆盖“数据仅供参考/展示用途，具体以官方发布为准”等关键点

```html
<!-- AttributionBar -->
<div class="fixed right-4 bottom-24 z-40
            bg-slate-800/70 backdrop-blur-xl px-3 py-2 rounded-lg
            border border-slate-400/20 shadow-md">
  <div class="flex items-center gap-3 text-xs">
    <span class="truncate max-w-[360px] text-slate-500">
      © Cesium · © ECMWF / CLDAS
    </span>
    <button class="text-slate-400 hover:text-slate-200 underline cursor-pointer"
            aria-label="查看数据来源">
      数据来源
    </button>
    <button class="text-slate-400 hover:text-slate-200 underline cursor-pointer"
            aria-label="查看免责声明">
      免责声明
    </button>
  </div>
</div>
```

---

## 六、数据展示组件

### 6.1 气象数据卡片 (WeatherCard)

```html
<div class="bg-slate-700/50 rounded-lg p-4 space-y-3">
  <!-- 标题行 -->
  <div class="flex items-center justify-between">
    <div class="flex items-center gap-2">
      <svg class="w-5 h-5 text-amber-400"><!-- Temperature Icon --></svg>
      <span class="text-sm font-medium text-slate-300">温度</span>
    </div>
    <span class="text-xs text-slate-500">实时</span>
  </div>

  <!-- 主数值 -->
  <div class="flex items-baseline gap-1">
    <span class="font-mono text-3xl font-semibold text-white">23.5</span>
    <span class="text-lg text-slate-400">°C</span>
  </div>

  <!-- 辅助信息 -->
  <div class="flex items-center gap-4 text-xs text-slate-500">
    <span>体感 25°C</span>
    <span>↑ 28°C</span>
    <span>↓ 18°C</span>
  </div>
</div>
```

### 6.2 风向风速卡片 (WindCard)

```html
<div class="bg-slate-700/50 rounded-lg p-4">
  <div class="flex items-center gap-4">
    <!-- 风向罗盘 -->
    <div class="relative w-16 h-16">
      <svg class="w-full h-full text-slate-600" viewBox="0 0 64 64">
        <circle cx="32" cy="32" r="30" fill="none" stroke="currentColor" stroke-width="2"/>
        <!-- 方位标记 -->
        <text x="32" y="10" text-anchor="middle" class="text-xs fill-slate-500">N</text>
        <text x="54" y="35" text-anchor="middle" class="text-xs fill-slate-500">E</text>
        <text x="32" y="60" text-anchor="middle" class="text-xs fill-slate-500">S</text>
        <text x="10" y="35" text-anchor="middle" class="text-xs fill-slate-500">W</text>
      </svg>
      <!-- 风向指针 -->
      <div class="absolute inset-0 flex items-center justify-center"
           style="transform: rotate(225deg)">
        <svg class="w-6 h-6 text-blue-400"><!-- Arrow Up --></svg>
      </div>
    </div>

    <!-- 风速数据 -->
    <div class="flex-1">
      <div class="text-sm text-slate-400">西南风</div>
      <div class="flex items-baseline gap-1 mt-1">
        <span class="font-mono text-2xl font-semibold text-white">12.5</span>
        <span class="text-sm text-slate-400">m/s</span>
      </div>
      <div class="text-xs text-slate-500 mt-1">阵风 18 m/s</div>
    </div>
  </div>
</div>
```

### 6.3 降水预报图表 (PrecipChart)

```html
<div class="bg-slate-700/50 rounded-lg p-4">
  <div class="flex items-center justify-between mb-3">
    <span class="text-sm font-medium text-slate-300">24小时降水预报</span>
    <span class="text-xs text-slate-500">mm</span>
  </div>

  <!-- 柱状图 -->
  <div class="flex items-end gap-1 h-24">
    <!-- 每小时一个柱子 -->
    <div class="flex-1 flex flex-col items-center gap-1">
      <div class="w-full bg-blue-500/60 rounded-t" style="height: 20%"></div>
      <span class="text-xs text-slate-600">00</span>
    </div>
    <div class="flex-1 flex flex-col items-center gap-1">
      <div class="w-full bg-blue-500/60 rounded-t" style="height: 35%"></div>
      <span class="text-xs text-slate-600">03</span>
    </div>
    <div class="flex-1 flex flex-col items-center gap-1">
      <div class="w-full bg-blue-500 rounded-t" style="height: 80%"></div>
      <span class="text-xs text-slate-400">06</span>
    </div>
    <!-- ... 更多时间点 -->
  </div>
</div>
```

### 6.4 风险等级指示器 (RiskIndicator)

```html
<div class="bg-slate-700/50 rounded-lg p-4">
  <div class="flex items-center justify-between mb-3">
    <span class="text-sm font-medium text-slate-300">滑坡风险</span>
    <span class="px-2 py-0.5 text-xs font-medium rounded-full
                 bg-amber-500/20 text-amber-400 border border-amber-500/30">
      中等
    </span>
  </div>

  <!-- 风险条 -->
  <div class="relative h-2 bg-slate-600 rounded-full overflow-hidden">
    <div class="absolute inset-y-0 left-0 w-full flex">
      <div class="flex-1 bg-green-500"></div>
      <div class="flex-1 bg-amber-500"></div>
      <div class="flex-1 bg-red-500"></div>
    </div>
  </div>
  <div class="absolute w-3 h-3 bg-white rounded-full border-2 border-slate-800
              top-1/2 -translate-y-1/2" style="left: 55%"></div>

  <!-- 影响因素 -->
  <div class="mt-3 space-y-1 text-xs text-slate-500">
    <div class="flex justify-between">
      <span>累计降水</span>
      <span class="text-slate-400">85mm (高)</span>
    </div>
    <div class="flex justify-between">
      <span>坡度</span>
      <span class="text-slate-400">25° (中)</span>
    </div>
  </div>
</div>
```

### 6.5 图例/色标 (Legend)

**渲染来源**：默认调色板见 2.1；当图层提供 `legend.json` 时，UI 必须按 `legend.json` 动态渲染图例（包括标题、单位、分级/渐变、标注）。

`legend.json` 示例：

```json
{
  "title": "降雪量",
  "unit": "mm",
  "type": "steps",
  "stops": [
    {"value": 0, "color": "#BFDBFE", "label": "0"},
    {"value": 10, "color": "#60A5FA", "label": "10"},
    {"value": 25, "color": "#2563EB", "label": "25"},
    {"value": 50, "color": "#7C3AED", "label": "50+"}
  ]
}
```

---

## 七、场景专属 UI

### 7.1 模式与状态机命名映射

| 状态机命名 | UI/设计术语 | 说明 |
|-----------|------------|------|
| Global | 全局 | 应用级状态：场景/路由、面板开关、用户/设置、全局快捷键 |
| Local | 点位仰视 | 局地状态：选点、天空视角、局地 HUD 与交互 |
| Event | 区域事件 | 事件状态：事件列表、风险区域、事件联动与筛选 |
| LayerGlobal | 图层全局 | 图层状态：图层清单、可见性/透明度、legend 渲染与加载状态 |

### 7.2 点位仰视模式 (Sky View)

**场景描述**：用户点击地球任意点，进入局地天空视角

**UI 元素**：
| 组件 | 位置 | 功能 |
|------|------|------|
| 天空穹顶 | 全屏背景 | 动态天空渲染 |
| 气象 HUD | 屏幕四角 | 温度/湿度/风速/气压 |
| 云层指示 | 顶部中央 | 云量/云高/云类型 |
| 返回按钮 | 左上角 | 返回地球视图 |

```html
<!-- Sky View HUD -->
<div class="fixed inset-0 pointer-events-none">
  <!-- 左上 - 返回 -->
  <button class="absolute top-4 left-4 pointer-events-auto
                 bg-slate-800/80 backdrop-blur-xl px-4 py-2 rounded-lg
                 border border-slate-400/20 flex items-center gap-2
                 hover:bg-slate-700/80 cursor-pointer">
    <svg class="w-4 h-4 text-slate-400"><!-- Back Arrow --></svg>
    <span class="text-sm text-slate-300">返回地球</span>
  </button>

  <!-- 右上 - 云层信息 -->
  <div class="absolute top-4 right-4 pointer-events-auto
              bg-slate-800/80 backdrop-blur-xl p-3 rounded-lg
              border border-slate-400/20 min-w-[160px]">
    <div class="text-xs text-slate-500 mb-1">云层</div>
    <div class="text-sm text-white">积云 Cu</div>
    <div class="text-xs text-slate-400 mt-1">云底 1500m · 云量 60%</div>
  </div>

  <!-- 底部 - 气象数据条 -->
  <div class="absolute bottom-4 left-1/2 -translate-x-1/2 pointer-events-auto
              bg-slate-800/80 backdrop-blur-xl px-6 py-3 rounded-xl
              border border-slate-400/20 flex items-center gap-8">
    <div class="text-center">
      <div class="font-mono text-xl text-white">23°C</div>
      <div class="text-xs text-slate-500">温度</div>
    </div>
    <div class="w-px h-8 bg-slate-600"></div>
    <div class="text-center">
      <div class="font-mono text-xl text-white">65%</div>
      <div class="text-xs text-slate-500">湿度</div>
    </div>
    <div class="w-px h-8 bg-slate-600"></div>
    <div class="text-center">
      <div class="font-mono text-xl text-white">SW 12</div>
      <div class="text-xs text-slate-500">风向风速</div>
    </div>
    <div class="w-px h-8 bg-slate-600"></div>
    <div class="text-center">
      <div class="font-mono text-xl text-white">1013</div>
      <div class="text-xs text-slate-500">气压 hPa</div>
    </div>
  </div>
</div>
```

### 7.3 区域事件模式 (Event Mode)

**场景描述**：叠加预报与监测数据，展示降雪/风险区域

**UI 元素**：
| 组件 | 位置 | 功能 |
|------|------|------|
| 事件列表 | 左侧面板 | 当前活跃事件 |
| 图例 | 右下角（安全区） | 由 `legend.json` 动态渲染色标说明 |
| 风险点标记 | 地图上 | 可点击查看详情 |

```html
<!-- 事件列表面板 -->
<aside class="fixed left-4 top-24 w-80 z-40
              bg-slate-800/80 backdrop-blur-xl
              border border-slate-400/20 rounded-xl overflow-hidden">
  <div class="p-4 border-b border-slate-700">
    <h2 class="font-semibold text-white">活跃事件</h2>
  </div>

  <div class="max-h-[400px] overflow-y-auto">
    <!-- 事件卡片 -->
    <div class="p-3 border-b border-slate-700/50 hover:bg-slate-700/30
                cursor-pointer transition-colors">
      <div class="flex items-start gap-3">
        <div class="w-2 h-2 mt-1.5 rounded-full bg-amber-500"></div>
        <div class="flex-1">
          <div class="text-sm font-medium text-white">华北降雪预警</div>
          <div class="text-xs text-slate-500 mt-1">
            预计 12:00 - 18:00 · 中到大雪
          </div>
          <div class="flex items-center gap-2 mt-2">
            <span class="px-1.5 py-0.5 text-xs rounded bg-amber-500/20
                         text-amber-400">黄色预警</span>
            <span class="text-xs text-slate-500">影响 3 省</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</aside>

<!-- 图例（根据 legend.json 动态渲染，示意） -->
<div class="fixed right-4 bottom-32 z-40
            bg-slate-800/80 backdrop-blur-xl p-3 rounded-lg
            border border-slate-400/20">
  <div class="text-xs text-slate-500 mb-2">降雪量 (mm)</div>
  <div class="flex items-center gap-1">
    <div class="w-6 h-3 rounded-sm bg-blue-200"></div>
    <div class="w-6 h-3 rounded-sm bg-blue-400"></div>
    <div class="w-6 h-3 rounded-sm bg-blue-600"></div>
    <div class="w-6 h-3 rounded-sm bg-purple-600"></div>
  </div>
  <div class="flex justify-between text-xs text-slate-600 mt-1">
    <span>0</span>
    <span>10</span>
    <span>25</span>
    <span>50+</span>
  </div>
</div>
```

---

## 八、Unreal Engine UMG 设计

### 8.1 UE UI 设计原则

1. **与 Web 端视觉一致**：使用相同色板和字体
2. **VR/大屏优化**：更大的点击区域和字号
3. **性能优先**：减少透明度叠加，优化材质
4. **3D 空间 UI**：支持 Widget Component 悬浮显示

### 8.2 UMG 色彩配置

```cpp
// UE Material Parameter Collection
// MPC_UIColors

FLinearColor PrimaryColor = FLinearColor(0.231f, 0.510f, 0.965f, 1.0f);    // #3B82F6
FLinearColor BackgroundColor = FLinearColor(0.059f, 0.090f, 0.165f, 0.9f); // #0F172A/90%
FLinearColor TextPrimary = FLinearColor(0.973f, 0.980f, 0.988f, 1.0f);     // #F8FAFC
FLinearColor TextSecondary = FLinearColor(0.580f, 0.639f, 0.722f, 1.0f);   // #94A3B8
FLinearColor BorderColor = FLinearColor(0.580f, 0.639f, 0.722f, 0.2f);     // #94A3B8/20%
```

### 8.3 UMG 组件规范

#### 飞行 HUD (Flight HUD)

```
┌─────────────────────────────────────────────────────────────┐
│  ALT: 8,500m        SPD: 450 km/h        HDG: 225° SW      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│                    ┌─────────────┐                          │
│                    │   准星/POI  │                          │
│                    └─────────────┘                          │
│                                                             │
│  ┌──────────┐                              ┌──────────────┐ │
│  │ 气象警告 │                              │  小地图      │ │
│  │ (左下)   │                              │  (右下)      │ │
│  └──────────┘                              └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

#### 气象警告面板

```cpp
// UMG Widget Blueprint: WBP_WeatherAlert

// 结构
- Canvas Panel (Root)
  - Border (Glass Background)
    - Vertical Box
      - Horizontal Box (Header)
        - Image (Warning Icon)
        - Text Block (Title)
      - Text Block (Description)
      - Progress Bar (Severity)

// 样式
Background: MPC_UIColors.BackgroundColor
Border: 2px, MPC_UIColors.BorderColor
Corner Radius: 8px
Padding: 16px
```

### 8.4 3D 空间 UI (Widget Component)

用于在 3D 场景中显示 POI 信息：

```cpp
// Actor: BP_WeatherPOI

// 组件结构
- Scene Root
  - Widget Component (WBP_POIMarker)
    - Draw Size: 200x80
    - Space: Screen (始终面向摄像机)
  - Billboard Component (Icon)

// WBP_POIMarker 内容
- Vertical Box
  - Text Block (Location Name)
  - Horizontal Box
    - Text Block (Temperature)
    - Text Block (Weather Condition)
```

---

## 九、图标规范

### 9.1 图标来源

| 用途 | 推荐图标库 | 风格 |
|------|------------|------|
| UI 操作 | Heroicons | Outline, 24x24 |
| 气象符号 | 自定义 SVG | Filled, 统一风格 |
| 品牌 Logo | Simple Icons | 官方 SVG |

### 9.2 气象图标集

```
☀️ 晴天      → sun.svg
🌤️ 多云      → cloud-sun.svg
☁️ 阴天      → cloud.svg
🌧️ 小雨      → cloud-rain.svg
⛈️ 雷暴      → cloud-lightning.svg
🌨️ 降雪      → cloud-snow.svg
🌫️ 雾霾      → fog.svg
💨 大风      → wind.svg
```

### 9.3 图标尺寸规范

| 场景 | 尺寸 | Tailwind |
|------|------|----------|
| 导航栏 | 20x20 | w-5 h-5 |
| 面板标题 | 20x20 | w-5 h-5 |
| 数据卡片 | 24x24 | w-6 h-6 |
| 大型展示 | 48x48 | w-12 h-12 |
| 地图标记 | 32x32 | w-8 h-8 |

---

## 十、动画与过渡

### 10.1 过渡时长

| 类型 | 时长 | 缓动函数 |
|------|------|----------|
| 颜色变化 | 150ms | ease-out |
| 透明度 | 200ms | ease-out |
| 位移/缩放 | 300ms | ease-in-out |
| 面板展开 | 300ms | ease-out |
| 页面切换 | 400ms | ease-in-out |

### 10.2 Tailwind 动画类

```html
<!-- 颜色过渡 -->
<button class="transition-colors duration-150">

<!-- 多属性过渡 -->
<div class="transition-all duration-300">

<!-- 面板滑入 -->
<aside class="transform transition-transform duration-300
              translate-x-0 data-[closed]:-translate-x-full">
```

### 10.3 减少动画 (Accessibility)

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## 十一、可访问性 (A11y)

### 11.1 对比度要求

| 元素 | 最小对比度 | 当前配色 |
|------|------------|----------|
| 正文文字 | 4.5:1 | #F8FAFC on #0F172A = 15.8:1 ✅ |
| 大标题 | 3:1 | #F8FAFC on #1E293B = 12.1:1 ✅ |
| 辅助文字 | 4.5:1 | #94A3B8 on #0F172A = 7.2:1 ✅ |
| 交互元素 | 3:1 | #3B82F6 on #0F172A = 4.8:1 ✅ |

### 11.2 键盘导航

```html
<!-- 可聚焦元素 -->
<button class="focus:outline-none focus:ring-2 focus:ring-blue-500
               focus:ring-offset-2 focus:ring-offset-slate-900">

<!-- Skip Link -->
<a href="#main-content"
   class="sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4
          bg-blue-500 text-white px-4 py-2 rounded-lg z-[100]">
  跳转到主内容
</a>
```

### 11.3 屏幕阅读器

```html
<!-- 图标按钮 -->
<button aria-label="设置">
  <svg class="w-5 h-5" aria-hidden="true">...</svg>
</button>

<!-- 实时数据更新 -->
<div aria-live="polite" aria-atomic="true">
  当前温度: 23.5°C
</div>

<!-- 图表替代文本 -->
<div role="img" aria-label="24小时降水预报柱状图，最高降水量出现在06时，约15毫米">
  <!-- Chart SVG -->
</div>
```

---

## 十二、Issue 关联参考

以下 Issues 在开发时应参考本 UI 设计规范：

### Web 客户端

| Issue | 组件 | 参考章节 |
|-------|------|----------|
| EP-19 | Web 基础框架 | 四、五 |
| EP-20 | 地球渲染 | 四 |
| EP-21 | 气象图层 | 六 |
| EP-22 | 点位仰视 | 七.2 |
| EP-23 | 区域事件 | 七.3 |
| EP-24 | 时间轴 | 五.3 |

### UE 客户端

| Issue | 组件 | 参考章节 |
|-------|------|----------|
| EP-25 | UE 基础框架 | 八 |
| EP-26 | 飞行控制 | 八.3 |
| EP-27 | 气象特效 | 八 |
| EP-28 | 灾害特效 | 八 |
| EP-29 | 交互系统 | 八.3, 八.4 |

---

## 附录 A：Tailwind 配置

```javascript
// tailwind.config.js
module.exports = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#3B82F6',
          hover: '#2563EB',
          light: '#60A5FA',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans SC', 'system-ui', 'sans-serif'],
        mono: ['Fira Code', 'JetBrains Mono', 'monospace'],
        display: ['Space Grotesk', 'Inter', 'sans-serif'],
      },
      backdropBlur: {
        xs: '2px',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
```

---

## 附录 B：设计资源

- **Figma 模板**：待创建
- **图标库**：Heroicons (https://heroicons.com)
- **字体**：Google Fonts
- **色彩工具**：Tailwind CSS Color Generator

---

*文档版本: v1.0 | 最后更新: 2026-01-14*
