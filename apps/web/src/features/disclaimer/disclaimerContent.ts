export type DisclaimerLocale = 'zh-CN' | 'en';

export type DisclaimerLink = {
  label: string;
  href: string;
};

export type DisclaimerItem = {
  title: string;
  description: string;
  links?: DisclaimerLink[];
};

export type DisclaimerSection = {
  title: string;
  items: DisclaimerItem[];
};

export type DisclaimerContent = {
  title: string;
  subtitle: string;
  sections: DisclaimerSection[];
};

export const DISCLAIMER_CONTENT: Record<DisclaimerLocale, DisclaimerContent> = {
  'zh-CN': {
    title: '数据来源与免责声明',
    subtitle: '归因信息与版权声明',
    sections: [
      {
        title: '数据来源与归因',
        items: [
          {
            title: 'ECMWF（气象数据）',
            description:
              '本平台部分气象数据（如温度、风场等）使用 ECMWF 产品/服务。请遵循 ECMWF 的使用条款与署名要求。',
            links: [
              { label: 'ECMWF', href: 'https://www.ecmwf.int/' },
              { label: 'Terms of Use', href: 'https://www.ecmwf.int/en/terms-use' },
            ],
          },
          {
            title: 'CLDAS（监测/陆面数据）',
            description:
              '本平台部分监测/陆面数据使用 CLDAS（China Land Data Assimilation System）相关产品。具体数据许可与署名要求以数据提供方说明为准。',
          },
          {
            title: '底图（Basemap）',
            description:
              '底图来源取决于当前选择/配置，可能包含 NASA GIBS、EOX Sentinel-2 Cloudless 等公共瓦片服务，或 Cesium ion / 自建底图服务。',
            links: [
              { label: 'NASA GIBS', href: 'https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs' },
              { label: 'EOX', href: 'https://eox.at/' },
            ],
          },
          {
            title: '地形（Terrain）',
            description:
              '三维地形可能使用 Cesium ion World Terrain（如已配置）或自建地形服务。请遵循对应服务的授权与署名要求。',
            links: [
              { label: 'Cesium ion', href: 'https://cesium.com/ion/' },
              { label: 'Cesium Terms', href: 'https://cesium.com/legal/terms-of-service/' },
            ],
          },
          {
            title: '三维引擎与渲染',
            description: '本平台 Web 端使用 CesiumJS 进行三维地球可视化渲染。',
            links: [{ label: 'CesiumJS', href: 'https://cesium.com/cesiumjs/' }],
          },
        ],
      },
      {
        title: '免责声明',
        items: [
          {
            title: '仅供参考',
            description:
              '本平台展示的数据与可视化结果仅供科研与公众参考，不构成任何形式的承诺、保证、建议或决策依据。',
          },
          {
            title: '不保证准确性/及时性',
            description:
              '我们不对数据的准确性、完整性、适用性、及时性提供明示或暗示的保证。数据可能存在缺测、延迟、偏差或更新不及时等情况。',
          },
          {
            title: '责任限制',
            description:
              '因使用或无法使用本平台而产生的任何直接或间接损失（包括但不限于业务损失、数据损失、利润损失等），我们不承担责任。',
          },
          {
            title: '第三方内容',
            description:
              '本平台可能引用第三方数据/服务（包括底图、地形与气象数据等）。第三方内容的版权与责任由其提供方承担。',
          },
        ],
      },
      {
        title: '版权与联系',
        items: [
          {
            title: '版权声明',
            description:
              '除另有说明外，本平台展示的第三方数据/底图/地形等内容版权归各自权利人所有。使用、转载或二次分发请遵循相应许可与署名要求。',
          },
          {
            title: '问题反馈',
            description: '如发现归因信息缺失或侵权风险，请在项目仓库提交 Issue 反馈。',
            links: [{ label: 'GitHub Repo', href: 'https://github.com/DankerMu/Digital-earth' }],
          },
        ],
      },
    ],
  },
  en: {
    title: 'Data Sources & Disclaimer',
    subtitle: 'Attribution and copyright notice',
    sections: [
      {
        title: 'Data Sources & Attribution',
        items: [
          {
            title: 'ECMWF (meteorological data)',
            description:
              'Some meteorological datasets may use ECMWF products/services. Please follow ECMWF terms and attribution requirements.',
            links: [
              { label: 'ECMWF', href: 'https://www.ecmwf.int/' },
              { label: 'Terms of Use', href: 'https://www.ecmwf.int/en/terms-use' },
            ],
          },
          {
            title: 'CLDAS (monitoring/land data)',
            description:
              'Some monitoring/land datasets may use CLDAS-related products. Please refer to the provider for license and attribution requirements.',
          },
          {
            title: 'Basemap',
            description:
              'Basemap sources depend on the current selection/configuration, such as NASA GIBS, EOX Sentinel-2 Cloudless, Cesium ion, or self-hosted services.',
            links: [
              { label: 'NASA GIBS', href: 'https://earthdata.nasa.gov/eosdis/science-system-description/eosdis-components/gibs' },
              { label: 'EOX', href: 'https://eox.at/' },
            ],
          },
          {
            title: 'Terrain',
            description:
              '3D terrain may use Cesium ion World Terrain (if configured) or self-hosted terrain services. Please follow the related license and attribution requirements.',
            links: [
              { label: 'Cesium ion', href: 'https://cesium.com/ion/' },
              { label: 'Cesium Terms', href: 'https://cesium.com/legal/terms-of-service/' },
            ],
          },
          {
            title: 'Rendering Engine',
            description: 'This web app uses CesiumJS for 3D globe rendering.',
            links: [{ label: 'CesiumJS', href: 'https://cesium.com/cesiumjs/' }],
          },
        ],
      },
      {
        title: 'Disclaimer',
        items: [
          {
            title: 'For reference only',
            description:
              'All data and visualizations are provided for research and public reference only, and do not constitute any warranty or advice.',
          },
          {
            title: 'No warranty',
            description:
              'We do not guarantee accuracy, completeness, applicability, or timeliness. Data may be missing, delayed, or biased.',
          },
          {
            title: 'Limitation of liability',
            description:
              'We are not liable for any direct or indirect damages resulting from the use or inability to use this platform.',
          },
          {
            title: 'Third-party content',
            description:
              'This platform may reference third-party data/services (basemap, terrain, weather data, etc.). Rights and responsibilities belong to the providers.',
          },
        ],
      },
      {
        title: 'Copyright & Contact',
        items: [
          {
            title: 'Copyright notice',
            description:
              'Unless otherwise stated, third-party data/basemap/terrain content belongs to the respective right holders. Follow related license and attribution requirements.',
          },
          {
            title: 'Feedback',
            description:
              'If attribution is missing or you have concerns, please file an issue in the project repository.',
            links: [{ label: 'GitHub Repo', href: 'https://github.com/DankerMu/Digital-earth' }],
          },
        ],
      },
    ],
  },
};

export type DisclaimerUiStrings = {
  openButtonAriaLabel: string;
  openButtonTitle: string;
  loadingDialogAriaLabel: string;
  loadingDialogTitle: string;
  loadingDialogSubtitle: string;
  loadingDialogBody: string;
  closeButtonAriaLabel: string;
  closeButtonText: string;
};

export const DISCLAIMER_UI_STRINGS: Record<DisclaimerLocale, DisclaimerUiStrings> = {
  'zh-CN': {
    openButtonAriaLabel: '打开数据来源与免责声明',
    openButtonTitle: '数据来源与免责声明',
    loadingDialogAriaLabel: '加载中',
    loadingDialogTitle: '加载中…',
    loadingDialogSubtitle: '正在加载数据来源与免责声明',
    loadingDialogBody: '请稍候…',
    closeButtonAriaLabel: '关闭弹窗',
    closeButtonText: '关闭',
  },
  en: {
    openButtonAriaLabel: 'Open Data Sources & Disclaimer',
    openButtonTitle: 'Data Sources & Disclaimer',
    loadingDialogAriaLabel: 'Loading',
    loadingDialogTitle: 'Loading…',
    loadingDialogSubtitle: 'Loading Data Sources & Disclaimer',
    loadingDialogBody: 'Please wait…',
    closeButtonAriaLabel: 'Close dialog',
    closeButtonText: 'Close',
  },
};
