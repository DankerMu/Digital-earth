import { useEffect, useMemo, useRef, useState } from 'react';

import { parseAttribution } from './parseAttribution';

type Props = {
  open: boolean;
  section: 'sources' | 'disclaimer';
  attributionText: string;
  version: string | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
};

const URL_REGEX = /(https?:\/\/[^\s)]+)/g;

function renderWithLinks(text: string) {
  const parts = text.split(URL_REGEX);
  return parts.map((part, index) => {
    if (part.match(URL_REGEX)) {
      return (
        <a
          key={`${part}-${index}`}
          href={part}
          target="_blank"
          rel="noreferrer"
          className="inlineLink"
        >
          {part}
        </a>
      );
    }
    return <span key={`${index}`}>{part}</span>;
  });
}

async function writeClipboardText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = text;
  textarea.setAttribute('readonly', 'true');
  textarea.style.position = 'fixed';
  textarea.style.top = '0';
  textarea.style.left = '0';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

export function AttributionModal({
  open,
  section,
  attributionText,
  version,
  loading,
  error,
  onRetry,
  onClose,
}: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const [copied, setCopied] = useState(false);

  const parsed = useMemo(() => parseAttribution(attributionText), [attributionText]);
  const title = section === 'sources' ? '数据来源' : '免责声明';
  const items = section === 'sources' ? parsed.sources : parsed.disclaimer;

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) setCopied(false);
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="modalOverlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <div className="modalHeader">
          <div>
            <h2 className="modalTitle">{title}</h2>
            <div className="modalMeta">
              {version ? `版本 v${version}` : null}
              {parsed.updatedAt ? ` · ${parsed.updatedAt}` : null}
            </div>
          </div>
          <div className="modalHeaderActions">
            <button
              type="button"
              className="modalButton"
              onClick={() => {
                void writeClipboardText(attributionText).then(() => {
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1200);
                });
              }}
              aria-label="复制归因信息"
            >
              {copied ? '已复制' : '复制'}
            </button>
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
          {error ? (
            <>
              <p className="modalError">加载失败：{error}</p>
              <button type="button" className="modalButton" onClick={onRetry}>
                重试
              </button>
            </>
          ) : null}

          {loading && !items.length ? (
            <p className="modalMeta">加载中…</p>
          ) : null}

          {!error && items.length ? (
            <>
              <p className="modalSectionTitle">
                {section === 'sources' ? 'Sources' : 'Disclaimer'}
              </p>
              <ul className="modalList">
                {items.map((line) => (
                  <li key={line} className="modalListItem">
                    {renderWithLinks(line)}
                  </li>
                ))}
              </ul>
            </>
          ) : null}

          {!error && !loading && !items.length ? (
            <p className="modalMeta">暂无内容</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

