import { lazy, Suspense, useCallback, useState } from 'react';

const DisclaimerDialog = lazy(() =>
  import('./DisclaimerDialog').then((module) => ({
    default: module.DisclaimerDialog,
  }))
);

function LoadingDialog({ onClose }: { onClose: () => void }) {
  return (
    <div
      className="modalOverlay"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label="加载中">
        <div className="modalHeader">
          <div>
            <h2 className="modalTitle">加载中…</h2>
            <div className="modalMeta">正在加载数据来源与免责声明</div>
          </div>
          <div className="modalHeaderActions">
            <button type="button" className="modalButton" onClick={onClose} aria-label="关闭弹窗">
              关闭
            </button>
          </div>
        </div>
        <div className="modalBody">
          <p className="modalMeta">请稍候…</p>
        </div>
      </div>
    </div>
  );
}

export function DisclaimerLauncher() {
  const [open, setOpen] = useState(false);
  const onClose = useCallback(() => setOpen(false), []);

  return (
    <>
      <button
        type="button"
        className="disclaimerFab"
        onClick={() => setOpen(true)}
        aria-label="打开数据来源与免责声明"
        title="数据来源与免责声明"
      >
        i
      </button>

      {open ? (
        <Suspense fallback={<LoadingDialog onClose={onClose} />}>
          <DisclaimerDialog open={open} onClose={onClose} />
        </Suspense>
      ) : null}
    </>
  );
}
