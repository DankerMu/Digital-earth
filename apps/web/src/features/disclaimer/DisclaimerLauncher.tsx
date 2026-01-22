import { useCallback, useState } from 'react';

import { DisclaimerDialog } from './DisclaimerDialog';
import { DISCLAIMER_UI_STRINGS, type DisclaimerLocale } from './disclaimerUiStrings';

type Props = {
  locale?: DisclaimerLocale;
};

export function DisclaimerLauncher({ locale = 'zh-CN' }: Props) {
  const [open, setOpen] = useState(false);

  const onOpen = useCallback(() => {
    setOpen(true);
  }, []);

  const onClose = useCallback(() => setOpen(false), []);
  const uiStrings = DISCLAIMER_UI_STRINGS[locale];

  return (
    <>
      <button
        type="button"
        className="disclaimerFab"
        onClick={onOpen}
        aria-label={uiStrings.openButtonAriaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={uiStrings.openButtonTitle}
      >
        i
      </button>

      <DisclaimerDialog open={open} onClose={onClose} locale={locale} />
    </>
  );
}
