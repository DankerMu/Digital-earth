import type { ProductDraft } from '../../state/productDraft';

export type ProductEditorValues = ProductDraft;

export type ProductEditorErrors = Partial<Record<keyof ProductEditorValues, string>> & {
  form?: string;
};

function normalizeText(value: string): string {
  return value.trim();
}

function toEpochMs(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const date = new Date(trimmed);
  const ms = date.getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function normalizeProductEditorValues(values: ProductEditorValues): ProductEditorValues {
  return {
    title: normalizeText(values.title),
    text: normalizeText(values.text),
    issued_at: normalizeText(values.issued_at),
    valid_from: normalizeText(values.valid_from),
    valid_to: normalizeText(values.valid_to),
    type: normalizeText(values.type),
    severity: normalizeText(values.severity),
  };
}

export function validateProductEditor(values: ProductEditorValues): ProductEditorErrors {
  const errors: ProductEditorErrors = {};

  const required: Array<keyof ProductEditorValues> = [
    'title',
    'text',
    'issued_at',
    'valid_from',
    'valid_to',
    'type',
  ];

  for (const field of required) {
    if (!normalizeText(values[field])) {
      errors[field] = '此项为必填';
    }
  }

  const issuedAtMs = toEpochMs(values.issued_at);
  if (normalizeText(values.issued_at) && issuedAtMs == null) {
    errors.issued_at = '请输入合法的时间';
  }

  const validFromMs = toEpochMs(values.valid_from);
  if (normalizeText(values.valid_from) && validFromMs == null) {
    errors.valid_from = '请输入合法的时间';
  }

  const validToMs = toEpochMs(values.valid_to);
  if (normalizeText(values.valid_to) && validToMs == null) {
    errors.valid_to = '请输入合法的时间';
  }

  if (validFromMs != null && validToMs != null && validFromMs >= validToMs) {
    errors.valid_to = '结束时间必须晚于开始时间';
  }

  if (issuedAtMs != null && validFromMs != null && issuedAtMs > validFromMs) {
    errors.issued_at = '发布时间需早于或等于有效开始时间';
  }

  return errors;
}

