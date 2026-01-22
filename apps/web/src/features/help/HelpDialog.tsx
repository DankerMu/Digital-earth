import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useModal } from '../../lib/useModal';
import type { HelpContent } from './helpContent';
import { HELP_UI_STRINGS, type HelpLocale } from './helpUiStrings';

type Props = {
  open: boolean;
  locale?: HelpLocale;
  onClose: () => void;
};

export function HelpDialog({ open, locale = 'zh-CN', onClose }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const [content, setContent] = useState<Record<HelpLocale, HelpContent> | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const { onOverlayMouseDown } = useModal({
    open,
    modalRef,
    initialFocusRef: closeButtonRef,
    onClose,
  });

  useEffect(() => {
    if (!open) return;
    if (content) return;

    let cancelled = false;
    setLoadError(null);

    void import('./helpContent')
      .then((module) => {
        if (cancelled) return;
        setContent(module.HELP_CONTENT);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : String(error));
      });

    return () => {
      cancelled = true;
    };
  }, [content, open]);

  if (!open) return null;

  const uiStrings = HELP_UI_STRINGS[locale];
  const dialogContent = content ? content[locale] : null;
  const dialogTitle = dialogContent?.title ?? uiStrings.loadingDialogTitle;
  const dialogSubtitle = dialogContent?.subtitle ?? uiStrings.loadingDialogSubtitle;
  const dialogLabel = dialogContent?.title ?? uiStrings.loadingDialogAriaLabel;

  return createPortal(
    <div
      className="modalOverlay"
      role="presentation"
      data-testid="help-overlay"
      onMouseDown={onOverlayMouseDown}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={dialogLabel}
        ref={modalRef}
      >
        <div className="modalHeader">
          <div>
            <h2 className="modalTitle">{dialogTitle}</h2>
            <div className="modalMeta">{dialogSubtitle}</div>
          </div>
          <div className="modalHeaderActions">
            <button
              type="button"
              className="modalButton"
              onClick={onClose}
              ref={closeButtonRef}
              aria-label={uiStrings.closeButtonAriaLabel}
            >
              {uiStrings.closeButtonText}
            </button>
          </div>
        </div>

        <div className="modalBody">
          {loadError ? (
            <p className="modalError">
              {uiStrings.loadErrorPrefix}: {loadError}
            </p>
          ) : dialogContent ? (
            dialogContent.sections.map((section) => (
              <section key={section.title} className="grid gap-2">
                <p className="modalSectionTitle">{section.title}</p>
                <ul className="modalList">
                  {section.items.map((item) => (
                    <li key={item.title} className="modalListItem">
                      <div className="font-semibold text-slate-100">{item.title}</div>
                      <div className="whitespace-pre-line text-slate-200">{item.description}</div>
                      {item.links?.length ? (
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                          {item.links.map((link) => (
                            <a
                              key={link.href}
                              href={link.href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inlineLink"
                            >
                              {link.label}
                            </a>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </section>
            ))
          ) : (
            <p className="modalMeta">{uiStrings.loadingDialogBody}</p>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

