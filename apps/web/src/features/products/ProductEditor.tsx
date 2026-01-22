import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useModal } from '../../lib/useModal';
import { createEmptyProductDraft, useProductDraftStore } from '../../state/productDraft';

import {
  normalizeProductEditorValues,
  validateProductEditor,
  type ProductEditorErrors,
  type ProductEditorValues,
} from './productEditorValidation';

export type { ProductEditorValues };

function hasErrors(errors: ProductEditorErrors): boolean {
  return Object.keys(errors).length > 0;
}

function fieldClasses(hasError: boolean): string {
  return [
    'mt-1 w-full rounded-lg border px-3 py-2 text-sm text-slate-100 shadow-sm outline-none transition',
    'bg-slate-950/30 placeholder:text-slate-500',
    hasError ? 'border-rose-400/40 focus:border-rose-400/60 focus:ring-2 focus:ring-rose-400/30' : 'border-slate-400/20 focus:border-blue-400/50 focus:ring-2 focus:ring-blue-400/30',
  ].join(' ');
}

type Props = {
  open: boolean;
  initialValues?: Partial<ProductEditorValues>;
  title?: string;
  onClose: () => void;
  onSubmit: (values: ProductEditorValues) => void | Promise<void>;
};

export function ProductEditor({
  open,
  initialValues,
  title = '产品编辑器',
  onClose,
  onSubmit,
}: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const baseId = useId();
  const [values, setValues] = useState<ProductEditorValues>(() => {
    const stored = useProductDraftStore.getState().draft;
    const base = stored ?? (initialValues ? { ...createEmptyProductDraft(), ...initialValues } : createEmptyProductDraft());
    return base;
  });
  const [errors, setErrors] = useState<ProductEditorErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');
  const [validatedOnce, setValidatedOnce] = useState(false);
  const savedDraftUpdatedAt = useProductDraftStore((state) => state.updatedAt);

  const fieldIds = useMemo(() => {
    return {
      title: `product-editor-title-${baseId}`,
      text: `product-editor-text-${baseId}`,
      issued_at: `product-editor-issued-at-${baseId}`,
      valid_from: `product-editor-valid-from-${baseId}`,
      valid_to: `product-editor-valid-to-${baseId}`,
      type: `product-editor-type-${baseId}`,
      severity: `product-editor-severity-${baseId}`,
    };
  }, [baseId]);

  const { onOverlayMouseDown } = useModal({
    open,
    modalRef,
    initialFocusRef: closeButtonRef,
    onClose,
  });

  useEffect(() => {
    if (!open) return;
    const stored = useProductDraftStore.getState().draft;
    const base = stored ?? (initialValues ? { ...createEmptyProductDraft(), ...initialValues } : createEmptyProductDraft());
    setValues(base);
    setErrors({});
    setSubmitError(null);
    setIsSubmitting(false);
    setSaveStatus('idle');
    setValidatedOnce(false);
  }, [initialValues, open]);

  useEffect(() => {
    if (saveStatus !== 'saved') return;
    const timer = window.setTimeout(() => setSaveStatus('idle'), 1600);
    return () => window.clearTimeout(timer);
  }, [saveStatus]);

  const updatedAtLabel = useMemo(() => {
    if (!savedDraftUpdatedAt) return null;
    const date = new Date(savedDraftUpdatedAt);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleString();
  }, [savedDraftUpdatedAt]);

  function updateField(field: keyof ProductEditorValues, value: string) {
    setValues((current) => {
      const next = { ...current, [field]: value };
      if (!validatedOnce) return next;
      setErrors(validateProductEditor(next));
      return next;
    });
  }

  async function handleSubmit() {
    setValidatedOnce(true);
    const nextErrors = validateProductEditor(values);
    setErrors(nextErrors);
    if (hasErrors(nextErrors)) return;

    setIsSubmitting(true);
    setSubmitError(null);

    try {
      const normalized = normalizeProductEditorValues(values);
      await onSubmit(normalized);
      useProductDraftStore.getState().clearDraft();
      onClose();
    } catch (error: unknown) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleSaveDraft() {
    useProductDraftStore.getState().setDraft(values);
    setSaveStatus('saved');
  }

  if (!open) return null;

  return createPortal(
    <div
      className="modalOverlay"
      role="presentation"
      data-testid="product-editor-overlay"
      onMouseDown={onOverlayMouseDown}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} ref={modalRef}>
        <div className="modalHeader">
          <div className="min-w-0">
            <h2 className="modalTitle">{title}</h2>
            <div className="modalMeta">
              {saveStatus === 'saved' ? '草稿已保存' : updatedAtLabel ? `草稿更新时间: ${updatedAtLabel}` : '填写产品基础信息并保存草稿'}
            </div>
          </div>
          <div className="modalHeaderActions">
            <button
              type="button"
              className="modalButton"
              onClick={() => {
                useProductDraftStore.getState().clearDraft();
                setValues(initialValues ? { ...createEmptyProductDraft(), ...initialValues } : createEmptyProductDraft());
                setErrors({});
                setSubmitError(null);
                setValidatedOnce(false);
              }}
              aria-label="清除草稿"
            >
              清除草稿
            </button>
            <button
              type="button"
              className="modalButton"
              onClick={onClose}
              ref={closeButtonRef}
              aria-label="关闭编辑器"
            >
              关闭
            </button>
          </div>
        </div>

        <div className="modalBody">
          <form
            className="grid gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSubmit();
            }}
          >
            {submitError ? (
              <div className="rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
                提交失败：{submitError}
              </div>
            ) : null}

            {errors.form ? (
              <div className="rounded-lg border border-rose-400/20 bg-rose-500/10 p-3 text-sm text-rose-200" role="alert">
                {errors.form}
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor={fieldIds.title} className="text-sm font-medium text-slate-200">
                  标题 <span className="text-rose-300">*</span>
                </label>
                <input
                  id={fieldIds.title}
                  name="title"
                  className={fieldClasses(Boolean(errors.title))}
                  value={values.title}
                  onChange={(event) => updateField('title', event.target.value)}
                  aria-invalid={Boolean(errors.title)}
                  aria-describedby={errors.title ? `${fieldIds.title}-error` : undefined}
                  placeholder="请输入标题"
                  autoComplete="off"
                />
                {errors.title ? (
                  <div id={`${fieldIds.title}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.title}
                  </div>
                ) : null}
              </div>

              <div>
                <label htmlFor={fieldIds.type} className="text-sm font-medium text-slate-200">
                  类型 <span className="text-rose-300">*</span>
                </label>
                <input
                  id={fieldIds.type}
                  name="type"
                  className={fieldClasses(Boolean(errors.type))}
                  value={values.type}
                  onChange={(event) => updateField('type', event.target.value)}
                  aria-invalid={Boolean(errors.type)}
                  aria-describedby={errors.type ? `${fieldIds.type}-error` : undefined}
                  placeholder="如：降雪、雷暴、洪水…"
                  autoComplete="off"
                />
                {errors.type ? (
                  <div id={`${fieldIds.type}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.type}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <div>
                <label htmlFor={fieldIds.issued_at} className="text-sm font-medium text-slate-200">
                  发布时间 <span className="text-rose-300">*</span>
                </label>
                <input
                  id={fieldIds.issued_at}
                  name="issued_at"
                  type="datetime-local"
                  className={fieldClasses(Boolean(errors.issued_at))}
                  value={values.issued_at}
                  onChange={(event) => updateField('issued_at', event.target.value)}
                  aria-invalid={Boolean(errors.issued_at)}
                  aria-describedby={errors.issued_at ? `${fieldIds.issued_at}-error` : undefined}
                />
                {errors.issued_at ? (
                  <div id={`${fieldIds.issued_at}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.issued_at}
                  </div>
                ) : null}
              </div>

              <div>
                <label htmlFor={fieldIds.valid_from} className="text-sm font-medium text-slate-200">
                  有效开始时间 <span className="text-rose-300">*</span>
                </label>
                <input
                  id={fieldIds.valid_from}
                  name="valid_from"
                  type="datetime-local"
                  className={fieldClasses(Boolean(errors.valid_from))}
                  value={values.valid_from}
                  onChange={(event) => updateField('valid_from', event.target.value)}
                  aria-invalid={Boolean(errors.valid_from)}
                  aria-describedby={errors.valid_from ? `${fieldIds.valid_from}-error` : undefined}
                />
                {errors.valid_from ? (
                  <div id={`${fieldIds.valid_from}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.valid_from}
                  </div>
                ) : null}
              </div>

              <div>
                <label htmlFor={fieldIds.valid_to} className="text-sm font-medium text-slate-200">
                  有效结束时间 <span className="text-rose-300">*</span>
                </label>
                <input
                  id={fieldIds.valid_to}
                  name="valid_to"
                  type="datetime-local"
                  className={fieldClasses(Boolean(errors.valid_to))}
                  value={values.valid_to}
                  onChange={(event) => updateField('valid_to', event.target.value)}
                  aria-invalid={Boolean(errors.valid_to)}
                  aria-describedby={errors.valid_to ? `${fieldIds.valid_to}-error` : undefined}
                />
                {errors.valid_to ? (
                  <div id={`${fieldIds.valid_to}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.valid_to}
                  </div>
                ) : null}
              </div>
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <div>
                <label htmlFor={fieldIds.severity} className="text-sm font-medium text-slate-200">
                  严重程度 <span className="text-slate-400">(可选)</span>
                </label>
                <select
                  id={fieldIds.severity}
                  name="severity"
                  className={fieldClasses(Boolean(errors.severity))}
                  value={values.severity}
                  onChange={(event) => updateField('severity', event.target.value)}
                  aria-invalid={Boolean(errors.severity)}
                >
                  <option value="">未设置</option>
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                </select>
                {errors.severity ? (
                  <div className="mt-1 text-xs text-rose-200" role="alert">
                    {errors.severity}
                  </div>
                ) : null}
              </div>

              <div className="rounded-lg border border-slate-400/10 bg-slate-900/20 p-3 text-xs text-slate-400">
                <div className="font-medium text-slate-200">校验规则</div>
                <ul className="mt-1 list-disc space-y-1 pl-4">
                  <li>必填字段不能为空</li>
                  <li>有效开始时间需早于有效结束时间</li>
                  <li>发布时间需早于或等于有效开始时间</li>
                </ul>
              </div>
            </div>

            <div>
              <label htmlFor={fieldIds.text} className="text-sm font-medium text-slate-200">
                正文 <span className="text-rose-300">*</span>
              </label>
              <textarea
                id={fieldIds.text}
                name="text"
                className={[fieldClasses(Boolean(errors.text)), 'min-h-32 resize-y'].join(' ')}
                value={values.text}
                onChange={(event) => updateField('text', event.target.value)}
                aria-invalid={Boolean(errors.text)}
                aria-describedby={errors.text ? `${fieldIds.text}-error` : undefined}
                placeholder="请输入正文内容"
              />
              {errors.text ? (
                <div id={`${fieldIds.text}-error`} className="mt-1 text-xs text-rose-200" role="alert">
                  {errors.text}
                </div>
              ) : null}
            </div>

            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-end">
              <button
                type="button"
                className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-3 py-2 text-sm text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                onClick={handleSaveDraft}
              >
                保存草稿
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="rounded-lg border border-blue-400/30 bg-blue-500/20 px-3 py-2 text-sm font-medium text-blue-100 hover:bg-blue-500/30 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
              >
                {isSubmitting ? '提交中…' : '提交'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>,
    document.body,
  );
}
