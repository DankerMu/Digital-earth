import { useCallback, useState } from 'react';

import { HelpDialog } from './HelpDialog';
import { HELP_UI_STRINGS, type HelpLocale } from './helpUiStrings';

type Props = {
  locale?: HelpLocale;
};

export function HelpLauncher({ locale = 'zh-CN' }: Props) {
  const [open, setOpen] = useState(false);

  const onOpen = useCallback(() => {
    setOpen(true);
  }, []);

  const onClose = useCallback(() => setOpen(false), []);
  const uiStrings = HELP_UI_STRINGS[locale];

  return (
    <>
      <button
        type="button"
        className="helpFab"
        onClick={onOpen}
        aria-label={uiStrings.openButtonAriaLabel}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={uiStrings.openButtonTitle}
      >
        ?
      </button>

      <HelpDialog open={open} onClose={onClose} locale={locale} />
    </>
  );
}

