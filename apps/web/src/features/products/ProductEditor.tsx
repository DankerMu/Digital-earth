import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { useModal } from '../../lib/useModal';
import { bboxFromLonLat, polygonAreaKm2, polygonHasSelfIntersections } from '../../lib/geo';
import { createEmptyProductDraft, getProductDraftStorageKey, useProductDraftStore } from '../../state/productDraft';

import {
  datetimeLocalToIso,
  isoToDatetimeLocal,
  normalizeProductEditorValues,
  validateProductEditor,
  type ProductEditorErrors,
  type ProductEditorSubmitValues,
  type ProductEditorValues,
} from './productEditorValidation';
import { HazardPolygonMap } from './HazardPolygonMap';

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

function createHazardId(): string {
  return `hazard-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

type Props = {
  open: boolean;
  productId?: string | number | null;
  initialValues?: Partial<ProductEditorValues>;
  title?: string;
  onClose: () => void;
  onSubmit: (values: ProductEditorSubmitValues) => void | Promise<void>;
};

export function ProductEditor({
  open,
  productId,
  initialValues,
  title = '产品编辑器',
  onClose,
  onSubmit,
}: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modalRef = useRef<HTMLDivElement | null>(null);
  const baseId = useId();
  const isEditing = typeof productId === 'number' || (typeof productId === 'string' && productId.trim().length > 0);
  const storageKey = useMemo(() => getProductDraftStorageKey(productId), [productId]);
  const storedDraft = useProductDraftStore(storageKey, (state) => state.draft);
  const baseValues = useMemo(() => {
    const merged = initialValues ? { ...createEmptyProductDraft(), ...initialValues } : createEmptyProductDraft();

    const normalizeDateTimeLocal = (value: unknown) => {
      if (typeof value !== 'string') return '';
      const trimmed = value.trim();
      if (!trimmed) return '';
      const parsedAsDateTimeLocal = datetimeLocalToIso(trimmed);
      if (parsedAsDateTimeLocal) {
        return isoToDatetimeLocal(parsedAsDateTimeLocal) ?? trimmed;
      }
      return isoToDatetimeLocal(trimmed) ?? trimmed;
    };

    return {
      ...merged,
      issued_at: normalizeDateTimeLocal(merged.issued_at),
      valid_from: normalizeDateTimeLocal(merged.valid_from),
      valid_to: normalizeDateTimeLocal(merged.valid_to),
    };
  }, [initialValues]);
  const [values, setValues] = useState<ProductEditorValues>(() => {
    if (isEditing) return baseValues;
    return useProductDraftStore.getState(storageKey).draft ?? baseValues;
  });
  const [activeHazardId, setActiveHazardId] = useState<string | null>(() => {
    const initialDraft = isEditing ? baseValues : useProductDraftStore.getState(storageKey).draft ?? baseValues;
    return initialDraft.hazards[0]?.id ?? null;
  });
  const [isDrawingHazard, setIsDrawingHazard] = useState(false);
  const [errors, setErrors] = useState<ProductEditorErrors>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved'>('idle');
  const [validatedOnce, setValidatedOnce] = useState(false);
  const [restoredDraft, setRestoredDraft] = useState(false);
  const savedDraftUpdatedAt = useProductDraftStore(storageKey, (state) => state.updatedAt);
  const titleId = `product-editor-dialog-title-${baseId}`;
  const descriptionId = `product-editor-dialog-description-${baseId}`;

  const fieldIds = useMemo(() => {
    return {
      title: `product-editor-title-${baseId}`,
      text: `product-editor-text-${baseId}`,
      issued_at: `product-editor-issued-at-${baseId}`,
      valid_from: `product-editor-valid-from-${baseId}`,
      valid_to: `product-editor-valid-to-${baseId}`,
      type: `product-editor-type-${baseId}`,
      severity: `product-editor-severity-${baseId}`,
      hazards: `product-editor-hazards-${baseId}`,
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
    const stored = useProductDraftStore.getState(storageKey).draft;
    const nextValues = !isEditing && stored ? stored : baseValues;
    setValues(nextValues);
    setActiveHazardId(nextValues.hazards[0]?.id ?? null);
    setIsDrawingHazard(false);
    setErrors({});
    setSubmitError(null);
    setIsSubmitting(false);
    setSaveStatus('idle');
    setValidatedOnce(false);
    setRestoredDraft(false);
  }, [baseValues, isEditing, open, storageKey]);

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

  type TextField = 'title' | 'text' | 'issued_at' | 'valid_from' | 'valid_to' | 'type' | 'severity';

  function updateValues(patch: Partial<ProductEditorValues>) {
    setValues((current) => {
      const next = { ...current, ...patch };
      if (!validatedOnce) return next;
      setErrors(validateProductEditor(next));
      return next;
    });
  }

  function updateField(field: TextField, value: string) {
    updateValues({ [field]: value } as Pick<ProductEditorValues, TextField>);
  }

  function updateHazards(
    update: (hazards: ProductEditorValues['hazards']) => ProductEditorValues['hazards'],
  ) {
    setValues((current) => {
      const hazards = update(current.hazards);
      const next = { ...current, hazards };
      if (!validatedOnce) return next;
      setErrors(validateProductEditor(next));
      return next;
    });
  }

  useEffect(() => {
    if (values.hazards.length === 0) {
      if (activeHazardId !== null) setActiveHazardId(null);
      return;
    }
    if (!activeHazardId || !values.hazards.some((hazard) => hazard.id === activeHazardId)) {
      setActiveHazardId(values.hazards[0]!.id);
    }
  }, [activeHazardId, values.hazards]);

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
      useProductDraftStore.getState(storageKey).clearDraft();
      onClose();
    } catch (error: unknown) {
      setSubmitError(error instanceof Error ? error.message : String(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleSaveDraft() {
    useProductDraftStore.getState(storageKey).setDraft(values);
    setSaveStatus('saved');
  }

  function handleRestoreDraft() {
    const draft = useProductDraftStore.getState(storageKey).draft;
    if (!draft) return;
    setValues(draft);
    setActiveHazardId(draft.hazards[0]?.id ?? null);
    setIsDrawingHazard(false);
    setErrors({});
    setSubmitError(null);
    setValidatedOnce(false);
    setRestoredDraft(true);
  }

  const hazardsSummary = useMemo(() => {
    return values.hazards.map((hazard) => {
      const bbox = bboxFromLonLat(hazard.vertices);
      const areaKm2 = polygonAreaKm2(hazard.vertices);
      const selfIntersecting =
        hazard.vertices.length >= 4 ? polygonHasSelfIntersections(hazard.vertices) : false;

      return {
        id: hazard.id,
        vertices: hazard.vertices,
        bbox,
        areaKm2,
        selfIntersecting,
        isComplete: hazard.vertices.length >= 3,
      };
    });
  }, [values.hazards]);

  const activeHazard = useMemo(() => {
    if (!activeHazardId) return null;
    return hazardsSummary.find((hazard) => hazard.id === activeHazardId) ?? null;
  }, [activeHazardId, hazardsSummary]);

  if (!open) return null;

  return createPortal(
    <div
      className="modalOverlay"
      role="presentation"
      data-testid="product-editor-overlay"
      onMouseDown={onOverlayMouseDown}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        ref={modalRef}
      >
        <div className="modalHeader">
          <div className="min-w-0">
            <h2 id={titleId} className="modalTitle">
              {title}
            </h2>
            <div id={descriptionId} className="modalMeta">
              {saveStatus === 'saved'
                ? '草稿已保存'
                : isEditing && updatedAtLabel && !restoredDraft
                  ? `发现旧草稿（更新时间: ${updatedAtLabel}），可选择恢复`
                  : updatedAtLabel
                    ? `草稿更新时间: ${updatedAtLabel}`
                    : '填写产品基础信息并保存草稿'}
            </div>
          </div>
          <div className="modalHeaderActions">
            {isEditing && storedDraft ? (
              <button
                type="button"
                className="modalButton"
                onClick={handleRestoreDraft}
                aria-label="恢复草稿"
              >
                恢复草稿
              </button>
            ) : null}
            <button
              type="button"
              className="modalButton"
              onClick={() => {
                useProductDraftStore.getState(storageKey).clearDraft();
                setValues(baseValues);
                setActiveHazardId(baseValues.hazards[0]?.id ?? null);
                setIsDrawingHazard(false);
                setErrors({});
                setSubmitError(null);
                setValidatedOnce(false);
                setRestoredDraft(false);
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
            noValidate
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
                  required
                  aria-required="true"
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
                  required
                  aria-required="true"
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
                  required
                  aria-required="true"
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
                  required
                  aria-required="true"
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
                  required
                  aria-required="true"
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
                  aria-describedby={errors.severity ? `${fieldIds.severity}-error` : undefined}
                >
                  <option value="">未设置</option>
                  <option value="low">低</option>
                  <option value="medium">中</option>
                  <option value="high">高</option>
                </select>
                {errors.severity ? (
                  <div id={`${fieldIds.severity}-error`} className="mt-1 text-xs text-rose-200" role="alert">
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

            <div className="rounded-lg border border-slate-400/10 bg-slate-900/10 p-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-200">
                    风险区域 <span className="text-rose-300">*</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-400">
                    点击地图添加顶点，拖拽顶点编辑位置；右键或按钮删除顶点；双击或按钮完成绘制。
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                    onClick={() => {
                      const id = createHazardId();
                      updateValues({
                        hazards: [...values.hazards, { id, vertices: [] }],
                      });
                      setActiveHazardId(id);
                      setIsDrawingHazard(true);
                    }}
                  >
                    新增区域
                  </button>
                  {activeHazard ? (
                    <button
                      type="button"
                      className="rounded-lg border border-rose-400/20 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rose-400"
                      onClick={() => {
                        const next = values.hazards.filter((hazard) => hazard.id !== activeHazard.id);
                        updateValues({ hazards: next });
                        setActiveHazardId(next[0]?.id ?? null);
                        setIsDrawingHazard(false);
                      }}
                      aria-label="删除当前风险区域"
                    >
                      删除当前
                    </button>
                  ) : null}
                </div>
              </div>

              {errors.hazards ? (
                <div id={`${fieldIds.hazards}-error`} className="mt-2 text-xs text-rose-200" role="alert">
                  {errors.hazards}
                </div>
              ) : null}

              <div className="mt-3 grid gap-3 md:grid-cols-2">
                <div className="grid gap-3">
                  <div className="grid gap-2">
                    {hazardsSummary.length === 0 ? (
                      <div className="text-sm text-slate-400">尚未添加风险区域。</div>
                    ) : (
                      <div className="grid gap-2">
                        {hazardsSummary.map((hazard, index) => {
                          const selected = hazard.id === activeHazardId;
                          const status = hazard.selfIntersecting
                            ? '自交'
                            : hazard.vertices.length < 3
                              ? `点数不足(${hazard.vertices.length}/3)`
                              : '已完成';

                          return (
                            <button
                              key={hazard.id}
                              type="button"
                              className={[
                                'flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400',
                                selected
                                  ? 'border-blue-400/60 bg-blue-500/10'
                                  : 'border-slate-400/10 bg-slate-950/10 hover:bg-slate-950/20',
                              ].join(' ')}
                              onClick={() => {
                                setActiveHazardId(hazard.id);
                                setIsDrawingHazard(false);
                              }}
                              aria-selected={selected}
                            >
                              <div className="min-w-0">
                                <div className="truncate font-medium text-slate-100">区域 {index + 1}</div>
                                <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
                                  <span>顶点: {hazard.vertices.length}</span>
                                  <span>
                                    面积:{' '}
                                    {hazard.areaKm2 == null ? '—' : `${hazard.areaKm2.toFixed(2)} km²`}
                                  </span>
                                  <span
                                    className={
                                      hazard.selfIntersecting ? 'text-rose-200' : 'text-slate-400'
                                    }
                                  >
                                    状态: {status}
                                  </span>
                                </div>
                              </div>
                              {selected ? (
                                <span className="shrink-0 rounded-md border border-blue-400/30 bg-blue-500/10 px-2 py-0.5 text-[11px] text-blue-100">
                                  当前
                                </span>
                              ) : null}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </div>

                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                      disabled={!activeHazard}
                      onClick={() => setIsDrawingHazard(true)}
                    >
                      {isDrawingHazard ? '绘制中…' : '开始/继续绘制'}
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-blue-400/30 bg-blue-500/20 px-2 py-1 text-xs text-blue-100 hover:bg-blue-500/30 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                      disabled={!isDrawingHazard}
                      onClick={() => setIsDrawingHazard(false)}
                    >
                      完成绘制
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                      disabled={!activeHazard || activeHazard.vertices.length === 0}
                      onClick={() => {
                        if (!activeHazard) return;
                        const nextVertices = activeHazard.vertices.slice(0, -1);
                        updateValues({
                          hazards: values.hazards.map((hazard) =>
                            hazard.id === activeHazard.id ? { ...hazard, vertices: nextVertices } : hazard,
                          ),
                        });
                      }}
                    >
                      删除最后顶点
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 disabled:cursor-not-allowed disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                      disabled={!activeHazard || activeHazard.vertices.length === 0}
                      onClick={() => {
                        if (!activeHazard) return;
                        updateValues({
                          hazards: values.hazards.map((hazard) =>
                            hazard.id === activeHazard.id ? { ...hazard, vertices: [] } : hazard,
                          ),
                        });
                      }}
                    >
                      清空顶点
                    </button>
                  </div>

                  <HazardPolygonMap
                    hazards={values.hazards}
                    activeHazardId={activeHazardId}
                    drawing={isDrawingHazard}
                    onSetActiveHazardId={(id) => {
                      setActiveHazardId(id);
                      setIsDrawingHazard(false);
                    }}
                    onFinishDrawing={() => setIsDrawingHazard(false)}
                    onDeleteVertex={(hazardId, vertexIndex) => {
                      updateHazards((hazards) =>
                        hazards.map((hazard) => {
                          if (hazard.id !== hazardId) return hazard;
                          return {
                            ...hazard,
                            vertices: hazard.vertices.filter((_, index) => index !== vertexIndex),
                          };
                        }),
                      );
                    }}
                    onChangeVertices={(hazardId, vertices) => {
                      updateHazards((hazards) =>
                        hazards.map((hazard) =>
                          hazard.id === hazardId ? { ...hazard, vertices } : hazard,
                        ),
                      );
                    }}
                  />
                </div>

                <div className="grid gap-3">
                  {!activeHazard ? (
                    <div className="rounded-lg border border-slate-400/10 bg-slate-950/10 p-3 text-sm text-slate-400">
                      请选择或新增一个风险区域以编辑顶点。
                    </div>
                  ) : (
                    <div className="grid gap-3">
                      <div className="rounded-lg border border-slate-400/10 bg-slate-950/10 p-3 text-xs text-slate-300">
                        <div className="grid gap-1">
                          <div>
                            顶点数: <span className="font-medium">{activeHazard.vertices.length}</span>
                          </div>
                          <div>
                            面积:{' '}
                            <span className="font-medium">
                              {activeHazard.areaKm2 == null ? '—' : `${activeHazard.areaKm2.toFixed(2)} km²`}
                            </span>
                          </div>
                          <div>
                            bbox:{' '}
                            <span className="font-medium">
                              {activeHazard.bbox
                                ? `lon[${activeHazard.bbox.min_x.toFixed(4)}, ${activeHazard.bbox.max_x.toFixed(4)}], lat[${activeHazard.bbox.min_y.toFixed(4)}, ${activeHazard.bbox.max_y.toFixed(4)}]`
                                : '—'}
                            </span>
                          </div>
                        </div>
                        {activeHazard.selfIntersecting ? (
                          <div className="mt-2 rounded-md border border-rose-400/20 bg-rose-500/10 p-2 text-rose-200">
                            检测到多边形自交，请调整顶点。
                          </div>
                        ) : null}
                        {activeHazard.vertices.length > 0 && activeHazard.vertices.length < 3 ? (
                          <div className="mt-2 rounded-md border border-amber-400/20 bg-amber-500/10 p-2 text-amber-100">
                            多边形至少需要 3 个顶点。
                          </div>
                        ) : null}
                      </div>

                      <div className="rounded-lg border border-slate-400/10 bg-slate-950/10 p-3">
                        <div className="flex items-center justify-between gap-2">
                          <div className="text-sm font-medium text-slate-200">顶点列表</div>
                          <button
                            type="button"
                            className="rounded-lg border border-slate-400/20 bg-slate-700/30 px-2 py-1 text-xs text-slate-200 hover:bg-slate-700/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-400"
                            onClick={() => {
                              const lastVertex = activeHazard.vertices[activeHazard.vertices.length - 1];
                              const nextVertex = lastVertex ? { ...lastVertex } : { lon: 116.391, lat: 39.9075 };
                              const nextVertices = [...activeHazard.vertices, nextVertex];
                              updateValues({
                                hazards: values.hazards.map((hazard) =>
                                  hazard.id === activeHazard.id
                                    ? { ...hazard, vertices: nextVertices }
                                    : hazard,
                                ),
                              });
                            }}
                          >
                            添加顶点
                          </button>
                        </div>

                        {activeHazard.vertices.length === 0 ? (
                          <div className="mt-2 text-sm text-slate-400">暂无顶点，可点击地图或按钮添加。</div>
                        ) : (
                          <div className="mt-2 grid gap-2">
                            {activeHazard.vertices.map((vertex, index) => {
                              const lonId = `${fieldIds.hazards}-lon-${activeHazard.id}-${index}`;
                              const latId = `${fieldIds.hazards}-lat-${activeHazard.id}-${index}`;
                              return (
                                <div
                                  key={`${activeHazard.id}-${index}`}
                                  className="grid grid-cols-[1fr_1fr_auto] items-center gap-2"
                                >
                                  <div>
                                    <label htmlFor={lonId} className="sr-only">
                                      顶点 {index + 1} 经度
                                    </label>
                                    <input
                                      id={lonId}
                                      type="number"
                                      step="0.0001"
                                      className={fieldClasses(false)}
                                      value={String(vertex.lon)}
                                      onChange={(event) => {
                                        const value = Number(event.target.value);
                                        if (!Number.isFinite(value)) return;
                                        const nextVertices = activeHazard.vertices.map((current, i) =>
                                          i === index ? { ...current, lon: value } : current,
                                        );
                                        updateValues({
                                          hazards: values.hazards.map((hazard) =>
                                            hazard.id === activeHazard.id
                                              ? { ...hazard, vertices: nextVertices }
                                              : hazard,
                                          ),
                                        });
                                      }}
                                    />
                                  </div>
                                  <div>
                                    <label htmlFor={latId} className="sr-only">
                                      顶点 {index + 1} 纬度
                                    </label>
                                    <input
                                      id={latId}
                                      type="number"
                                      step="0.0001"
                                      className={fieldClasses(false)}
                                      value={String(vertex.lat)}
                                      onChange={(event) => {
                                        const value = Number(event.target.value);
                                        if (!Number.isFinite(value)) return;
                                        const nextVertices = activeHazard.vertices.map((current, i) =>
                                          i === index ? { ...current, lat: value } : current,
                                        );
                                        updateValues({
                                          hazards: values.hazards.map((hazard) =>
                                            hazard.id === activeHazard.id
                                              ? { ...hazard, vertices: nextVertices }
                                              : hazard,
                                          ),
                                        });
                                      }}
                                    />
                                  </div>
                                  <button
                                    type="button"
                                    className="rounded-lg border border-rose-400/20 bg-rose-500/10 px-2 py-1 text-xs text-rose-200 hover:bg-rose-500/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-rose-400"
                                    onClick={() => {
                                      updateValues({
                                        hazards: values.hazards.map((hazard) => {
                                          if (hazard.id !== activeHazard.id) return hazard;
                                          return {
                                            ...hazard,
                                            vertices: hazard.vertices.filter((_, i) => i !== index),
                                          };
                                        }),
                                      });
                                    }}
                                    aria-label={`删除顶点 ${index + 1}`}
                                  >
                                    删除
                                  </button>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
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
                required
                aria-required="true"
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
