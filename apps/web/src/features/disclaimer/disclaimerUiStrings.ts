export type DisclaimerLocale = 'zh-CN' | 'en';

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

