import { useEffect, useRef } from 'react';

import { DISCLAIMER_CONTENT, type DisclaimerLocale } from './disclaimerContent';

type Props = {
  open: boolean;
  locale?: DisclaimerLocale;
  onClose: () => void;
};

export function DisclaimerDialog({ open, locale = 'zh-CN', onClose }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const content = DISCLAIMER_CONTENT[locale];

  return (
    <div
      className="modalOverlay"
      role="presentation"
      data-testid="disclaimer-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={content.title}
      >
        <div className="modalHeader">
          <div>
            <h2 className="modalTitle">{content.title}</h2>
            <div className="modalMeta">{content.subtitle}</div>
          </div>
          <div className="modalHeaderActions">
            <button
              type="button"
              className="modalButton"
              onClick={onClose}
              ref={closeButtonRef}
              aria-label="关闭弹窗"
            >
              关闭
            </button>
          </div>
        </div>

        <div className="modalBody">
          {content.sections.map((section) => (
            <section key={section.title} className="grid gap-2">
              <p className="modalSectionTitle">{section.title}</p>
              <ul className="modalList">
                {section.items.map((item) => (
                  <li key={item.title} className="modalListItem">
                    <div className="font-semibold text-slate-100">{item.title}</div>
                    <div className="text-slate-200">{item.description}</div>
                    {item.links?.length ? (
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                        {item.links.map((link) => (
                          <a
                            key={link.href}
                            href={link.href}
                            target="_blank"
                            rel="noreferrer"
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
          ))}
        </div>
      </div>
    </div>
  );
}

