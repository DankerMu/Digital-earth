import type { HelpLocale } from './helpUiStrings';

export type HelpLink = {
  label: string;
  href: string;
};

export type HelpItem = {
  title: string;
  description: string;
  links?: HelpLink[];
};

export type HelpSection = {
  title: string;
  items: HelpItem[];
};

export type HelpContent = {
  title: string;
  subtitle: string;
  sections: HelpSection[];
};

export const HELP_CONTENT: Record<HelpLocale, HelpContent> = {
  'zh-CN': {
    title: '用户帮助',
    subtitle: '三场景操作指南与常见问题',
    sections: [
      {
        title: '三场景操作指南（Web）',
        items: [
          {
            title: '点位仰视模式（Local mode）',
            description: [
              '进入：在地球上双击，或按住 Ctrl 单击任意位置，进入局地（Local）视图。',
              '仰视：在「局地信息」面板的「相机视角」中选择「仰视」。也可以切换「平视 / 自由」。',
              '退出：点击面板中的「返回」或信息面板的「返回上一视图」。',
            ].join('\n'),
          },
          {
            title: '锁层模式（LayerGlobal mode）',
            description: [
              '进入：在左侧「图层」列表中点击任意图层；或在 Local 模式点击「锁定当前层」。',
              '用途：专注查看单个图层的渲染效果，并可调整可见性与透明度。',
              '退出：点击信息面板的「返回上一视图」。',
            ].join('\n'),
          },
          {
            title: '事件模式（Event mode）',
            description: [
              '进入：打开信息面板 →「当前」→「事件列表」，点击任意事件进入。',
              '浏览：事件被选中后，可在地图上查看相关标注；点击点位可查看该事件下的风险/信息（如有）。',
              '退出：点击信息面板的「返回上一视图」。',
            ].join('\n'),
          },
        ],
      },
      {
        title: '常见问题（FAQ）',
        items: [
          {
            title: '数据缺失处理',
            description: [
              '当图层出现灰显或提示「数据缺失，已降级展示。」时，表示当前时间/区域可能缺测或请求失败。',
              '建议：切换时间帧；尝试其他图层；检查网络/接口是否可用；必要时刷新页面重试。',
            ].join('\n'),
          },
          {
            title: '性能模式切换',
            description: [
              '位置：信息面板 →「设置」→「性能模式」。',
              'Low 模式会减少粒子与风矢密度，并关闭体云/建筑（如有），以提升低性能设备体验。',
              '可结合右侧 FPS 指标判断是否需要切换。',
            ].join('\n'),
          },
          {
            title: '数据归因说明',
            description: [
              '页面底部的「归因与数据来源」栏会显示当前数据/底图/引擎的归因摘要。',
              '可点击「数据来源」与「免责声明」查看详细说明。',
              '右下角的「i」按钮也可快速查看数据来源与免责声明（静态说明）。',
            ].join('\n'),
            links: [
              { label: 'GitHub Repo', href: 'https://github.com/DankerMu/Digital-earth' },
            ],
          },
        ],
      },
    ],
  },
  en: {
    title: 'Help',
    subtitle: 'Workflows and FAQs',
    sections: [
      {
        title: 'Core Workflows (Web)',
        items: [
          {
            title: 'Local mode (Upward view)',
            description: [
              'Enter: double-click on the globe, or Ctrl + Click anywhere to enter Local mode.',
              'Upward view: in the “Local info” panel, switch camera perspective to “Upward” (or “Forward / Free”).',
              'Exit: use “Back” in the panel or “Back to previous view” in the info panel.',
            ].join('\n'),
          },
          {
            title: 'Layer lock mode (LayerGlobal mode)',
            description: [
              'Enter: click any layer in the Layer tree; or click “Lock current layer” in Local mode.',
              'Purpose: focus on a single layer and adjust visibility/opacity.',
              'Exit: click “Back to previous view” in the info panel.',
            ].join('\n'),
          },
          {
            title: 'Event mode',
            description: [
              'Enter: Info panel → “Current” → “Event list”, then select an event.',
              'Explore: after selecting an event, related markers may appear on the map; click POIs to inspect event-specific details (if available).',
              'Exit: click “Back to previous view” in the info panel.',
            ].join('\n'),
          },
        ],
      },
      {
        title: 'FAQ',
        items: [
          {
            title: 'Missing data',
            description: [
              'If a layer is grayed out or shows a missing data message, the selected time/area may be unavailable or the request failed.',
              'Try switching time frames, trying another layer, checking network/API status, or refreshing the page.',
            ].join('\n'),
          },
          {
            title: 'Performance mode',
            description: [
              'Where: Info panel → “Settings” → “Performance mode”.',
              'Low reduces particle density and disables heavy effects (e.g. volumetric clouds/buildings) to improve performance.',
              'Use the FPS indicator to decide which mode to use.',
            ].join('\n'),
          },
          {
            title: 'Attribution',
            description: [
              'The footer “Attribution & sources” shows a summary for active data/basemap/engine.',
              'Use “Sources” and “Disclaimer” for full details.',
              'The “i” button in the bottom-right also provides a quick static overview.',
            ].join('\n'),
            links: [
              { label: 'GitHub Repo', href: 'https://github.com/DankerMu/Digital-earth' },
            ],
          },
        ],
      },
    ],
  },
};

