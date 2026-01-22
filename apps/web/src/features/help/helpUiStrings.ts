export type HelpLocale = 'zh-CN' | 'en';

export type HelpUiStrings = {
  openButtonAriaLabel: string;
  openButtonTitle: string;
  loadingDialogAriaLabel: string;
  loadingDialogTitle: string;
  loadingDialogSubtitle: string;
  loadingDialogBody: string;
  loadErrorPrefix: string;
  loadErrorMessage: string;
  retryButtonText: string;
  closeButtonAriaLabel: string;
  closeButtonText: string;
};

export const HELP_UI_STRINGS: Record<HelpLocale, HelpUiStrings> = {
  'zh-CN': {
    openButtonAriaLabel: '打开用户帮助',
    openButtonTitle: '用户帮助',
    loadingDialogAriaLabel: '加载中',
    loadingDialogTitle: '加载中…',
    loadingDialogSubtitle: '正在加载用户帮助',
    loadingDialogBody: '请稍候…',
    loadErrorPrefix: '加载失败',
    loadErrorMessage: '加载用户帮助失败，请重试。',
    retryButtonText: '重试',
    closeButtonAriaLabel: '关闭弹窗',
    closeButtonText: '关闭',
  },
  en: {
    openButtonAriaLabel: 'Open help',
    openButtonTitle: 'Help',
    loadingDialogAriaLabel: 'Loading',
    loadingDialogTitle: 'Loading…',
    loadingDialogSubtitle: 'Loading help content',
    loadingDialogBody: 'Please wait…',
    loadErrorPrefix: 'Failed to load',
    loadErrorMessage: 'Unable to load help content. Please try again.',
    retryButtonText: 'Retry',
    closeButtonAriaLabel: 'Close dialog',
    closeButtonText: 'Close',
  },
};
