import { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useModal } from '../../lib/useModal';
import type { HelpContent } from './helpContent';
import { HELP_UI_STRINGS, type HelpLocale } from './helpUiStrings';

type Props = {
  open: boolean;
  locale?: HelpLocale;
  onClose: () => void;
};

function sanitizeHttpHref(href: string): string | null {
  const trimmed = href.trim();
  if (!trimmed) return null;

  try {
    const url = new URL(trimmed, 'http://localhost');
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    return trimmed;
  } catch {
    return null;
  }
}

export function HelpDialog({ open, locale = 'zh-CN', onClose }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const [content, setContent] = useState<Record<HelpLocale, HelpContent> | null>(null);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [loadAttempts, setLoadAttempts] = useState(0);
  const rawTitleId = useId();
  const rawSubtitleId = useId();
  const rawErrorId = useId();

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
        const normalizedError = error instanceof Error ? error : new Error(String(error));
        console.error('[HelpDialog] Failed to load help content', normalizedError);
        setLoadError(normalizedError);
      });

    return () => {
      cancelled = true;
    };
  }, [content, loadAttempts, open]);

  if (!open) return null;

  const uiStrings = HELP_UI_STRINGS[locale];
  const dialogContent = content ? content[locale] : null;
  const dialogTitle =
    dialogContent?.title ?? (loadError ? uiStrings.loadErrorPrefix : uiStrings.loadingDialogTitle);
  const dialogSubtitle =
    dialogContent?.subtitle ??
    (loadError ? '' : uiStrings.loadingDialogSubtitle);
  const dialogTitleId = `help-dialog-title-${rawTitleId}`;
  const dialogSubtitleId = `help-dialog-subtitle-${rawSubtitleId}`;
  const dialogErrorId = `help-dialog-error-${rawErrorId}`;
  const dialogDescribedById = loadError ? dialogErrorId : dialogSubtitleId;

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
        aria-labelledby={dialogTitleId}
        aria-describedby={dialogDescribedById}
        ref={modalRef}
      >
        <div className="modalHeader">
          <div>
            <h2 id={dialogTitleId} className="modalTitle">
              {dialogTitle}
            </h2>
            <div id={dialogSubtitleId} className="modalMeta">
              {dialogSubtitle}
            </div>
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
            <>
              <p id={dialogErrorId} className="modalError">
                {uiStrings.loadErrorMessage}
              </p>
              <button
                type="button"
                className="modalButton"
                onClick={() => {
                  setLoadError(null);
                  setLoadAttempts((attempts) => attempts + 1);
                }}
              >
                {uiStrings.retryButtonText}
              </button>
            </>
          ) : dialogContent ? (
            dialogContent.sections.map((section) => (
              <section key={section.title} className="grid gap-2">
                <h3 className="modalSectionTitle">{section.title}</h3>
                <ul className="modalList">
                  {section.items.map((item) => (
                    <li key={item.title} className="modalListItem">
                      <div className="font-semibold text-slate-100">{item.title}</div>
                      <div className="whitespace-pre-line text-slate-200">{item.description}</div>
                      {item.links?.length ? (
                        <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                          {item.links.map((link) => {
                            const safeHref = sanitizeHttpHref(link.href);
                            if (!safeHref) return null;

                            return (
                              <a
                                key={safeHref}
                                href={safeHref}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inlineLink"
                              >
                                {link.label}
                              </a>
                            );
                          })}
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
