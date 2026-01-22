import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';

import { DISCLAIMER_UI_STRINGS, type DisclaimerLocale } from './disclaimerContent';

const DisclaimerDialog = lazy(() =>
  import('./DisclaimerDialog').then((module) => ({
    default: module.DisclaimerDialog,
  }))
);

function LoadingDialog({ onClose, locale }: { onClose: () => void; locale: DisclaimerLocale }) {
  const uiStrings = DISCLAIMER_UI_STRINGS[locale];

  return (
    <div
      className="modalOverlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={uiStrings.loadingDialogAriaLabel}>
        <div className="modalHeader">
          <div>
            <h2 className="modalTitle">{uiStrings.loadingDialogTitle}</h2>
            <div className="modalMeta">{uiStrings.loadingDialogSubtitle}</div>
          </div>
          <div className="modalHeaderActions">
            <button
              type="button"
              className="modalButton"
              onClick={onClose}
              aria-label={uiStrings.closeButtonAriaLabel}
            >
              {uiStrings.closeButtonText}
            </button>
          </div>
        </div>
        <div className="modalBody">
          <p className="modalMeta">{uiStrings.loadingDialogBody}</p>
        </div>
      </div>
    </div>
  );
}

type Props = {
  locale?: DisclaimerLocale;
};

export function DisclaimerLauncher({ locale = 'zh-CN' }: Props) {
  const [open, setOpen] = useState(false);
  const previouslyFocusedElementRef = useRef<HTMLElement | null>(null);

  const onOpen = useCallback(() => {
    previouslyFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setOpen(true);
  }, []);

  const onClose = useCallback(() => setOpen(false), []);
  const uiStrings = DISCLAIMER_UI_STRINGS[locale];

  useEffect(() => {
    if (open) return;

    const elementToRestore = previouslyFocusedElementRef.current;
    if (elementToRestore && document.contains(elementToRestore)) {
      elementToRestore.focus();
    }
    previouslyFocusedElementRef.current = null;
  }, [open]);

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

      {open ? (
        <Suspense fallback={<LoadingDialog onClose={onClose} locale={locale} />}>
          <DisclaimerDialog open={open} onClose={onClose} locale={locale} />
        </Suspense>
      ) : null}
    </>
  );
}
