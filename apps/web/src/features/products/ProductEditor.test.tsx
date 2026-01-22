import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

const NEW_STORAGE_KEY = 'digital-earth.productDraft.new';
const PRODUCT_STORAGE_KEY = 'digital-earth.productDraft.1';

async function importFreshEditor() {
  vi.resetModules();
  return await import('./ProductEditor');
}

describe('ProductEditor', () => {
  it('validateProductEditor reports invalid time values', async () => {
    vi.resetModules();
    const { validateProductEditor } = await import('./productEditorValidation');
    const errors = validateProductEditor({
      title: 't',
      type: 'snow',
      severity: '',
      text: 'body',
      issued_at: 'not-a-date',
      valid_from: 'still-not-a-date',
      valid_to: 'nope',
    });

    expect(errors.issued_at).toBe('请输入合法的时间');
    expect(errors.valid_from).toBe('请输入合法的时间');
    expect(errors.valid_to).toBe('请输入合法的时间');
  });

  it('shows required field errors and blocks submit', async () => {
    localStorage.removeItem(NEW_STORAGE_KEY);
    const { ProductEditor } = await importFreshEditor();
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(<ProductEditor open onClose={onClose} onSubmit={onSubmit} />);

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '提交' }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getAllByText('此项为必填')).toHaveLength(6);
  });

  it('validates time ordering rules', async () => {
    localStorage.removeItem(NEW_STORAGE_KEY);
    const { ProductEditor } = await importFreshEditor();
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(<ProductEditor open onClose={onClose} onSubmit={onSubmit} />);

    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/标题/), '测试产品');
    await user.type(screen.getByLabelText(/类型/), '降雪');
    await user.type(screen.getByLabelText(/正文/), '这里是正文');

    await user.type(screen.getByLabelText(/发布时间/), '2026-01-01T03:00');
    await user.type(screen.getByLabelText(/有效开始时间/), '2026-01-01T02:00');
    await user.type(screen.getByLabelText(/有效结束时间/), '2026-01-01T01:00');

    await user.click(screen.getByRole('button', { name: '提交' }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByText('结束时间必须晚于开始时间')).toBeInTheDocument();
    const alerts = await screen.findAllByRole('alert');
    expect(alerts.map((node) => node.textContent)).toContain('发布时间需早于或等于有效开始时间');
  });

  it('submits normalized values, clears draft, and closes', async () => {
    localStorage.removeItem(NEW_STORAGE_KEY);
    const { ProductEditor } = await importFreshEditor();
    const onSubmit = vi.fn();
    const onClose = vi.fn();

    render(<ProductEditor open onClose={onClose} onSubmit={onSubmit} />);

    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/标题/), '  测试产品  ');
    await user.type(screen.getByLabelText(/类型/), '  降雪  ');
    await user.selectOptions(screen.getByLabelText(/严重程度/), 'high');
    await user.type(screen.getByLabelText(/正文/), '  这里是正文  ');

    await user.type(screen.getByLabelText(/发布时间/), '2026-01-01T00:00');
    await user.type(screen.getByLabelText(/有效开始时间/), '2026-01-01T00:00');
    await user.type(screen.getByLabelText(/有效结束时间/), '2026-01-02T00:00');

    await user.click(screen.getByRole('button', { name: '保存草稿' }));
    expect(screen.getByText('草稿已保存')).toBeInTheDocument();
    expect(localStorage.getItem(NEW_STORAGE_KEY)).not.toBeNull();

    await user.click(screen.getByRole('button', { name: '提交' }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    expect(onSubmit).toHaveBeenCalledWith({
      title: '测试产品',
      type: '降雪',
      severity: 'high',
      text: '这里是正文',
      issued_at: '2026-01-01T00:00:00.000Z',
      valid_from: '2026-01-01T00:00:00.000Z',
      valid_to: '2026-01-02T00:00:00.000Z',
    });

    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });

    expect(localStorage.getItem(NEW_STORAGE_KEY)).toBeNull();
  });

  it('restores a saved draft after module reload', async () => {
    localStorage.removeItem(NEW_STORAGE_KEY);
    const { ProductEditor: ProductEditor1 } = await importFreshEditor();

    const first = render(<ProductEditor1 open onClose={() => {}} onSubmit={() => {}} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/标题/), 'Draft title');
    await user.type(screen.getByLabelText(/类型/), 'storm');
    await user.type(screen.getByLabelText(/正文/), 'draft body');
    await user.type(screen.getByLabelText(/发布时间/), '2026-01-01T00:00');
    await user.type(screen.getByLabelText(/有效开始时间/), '2026-01-01T01:00');
    await user.type(screen.getByLabelText(/有效结束时间/), '2026-01-01T02:00');
    await user.click(screen.getByRole('button', { name: '保存草稿' }));

    expect(localStorage.getItem(NEW_STORAGE_KEY)).not.toBeNull();

    first.unmount();

    // Simulate a page refresh by re-importing modules.
    const { ProductEditor: ProductEditor2 } = await importFreshEditor();

    render(<ProductEditor2 open onClose={() => {}} onSubmit={() => {}} />);

    expect(screen.getByLabelText(/标题/)).toHaveValue('Draft title');
    expect(screen.getByLabelText(/类型/)).toHaveValue('storm');
    expect(screen.getByLabelText(/正文/)).toHaveValue('draft body');
  });

  it('adds dialog labeling and required attributes', async () => {
    const { ProductEditor } = await importFreshEditor();

    render(<ProductEditor open onClose={() => {}} onSubmit={() => {}} />);

    const dialog = screen.getByRole('dialog');
    const titleId = dialog.getAttribute('aria-labelledby');
    const descriptionId = dialog.getAttribute('aria-describedby');

    expect(titleId).toBeTruthy();
    expect(descriptionId).toBeTruthy();
    expect(document.getElementById(titleId ?? '')).toHaveTextContent('产品编辑器');
    expect(document.getElementById(descriptionId ?? '')).toBeInTheDocument();

    expect(screen.getByLabelText(/标题/)).toBeRequired();
    expect(screen.getByLabelText(/标题/)).toHaveAttribute('aria-required', 'true');
    expect(screen.getByLabelText(/类型/)).toBeRequired();
    expect(screen.getByLabelText(/正文/)).toBeRequired();
    expect(screen.getByLabelText(/发布时间/)).toBeRequired();
    expect(screen.getByLabelText(/有效开始时间/)).toBeRequired();
    expect(screen.getByLabelText(/有效结束时间/)).toBeRequired();
  });

  it('prefers initialValues when editing and allows restoring draft', async () => {
    localStorage.removeItem(PRODUCT_STORAGE_KEY);
    localStorage.setItem(
      PRODUCT_STORAGE_KEY,
      JSON.stringify({
        draft: {
          title: 'Draft title',
          type: 'storm',
          severity: '',
          text: 'draft body',
          issued_at: '2026-01-01T00:00',
          valid_from: '2026-01-01T01:00',
          valid_to: '2026-01-01T02:00',
        },
        updatedAt: 123,
      }),
    );

    const { ProductEditor } = await importFreshEditor();

    render(
      <ProductEditor
        open
        productId="1"
        initialValues={{
          title: 'Initial title',
          type: 'snow',
          severity: '',
          text: 'initial body',
          issued_at: '2026-01-01T00:00:00Z',
          valid_from: '2026-01-01T01:00:00Z',
          valid_to: '2026-01-01T02:00:00Z',
        }}
        onClose={() => {}}
        onSubmit={() => {}}
      />,
    );

    expect(screen.getByLabelText(/标题/)).toHaveValue('Initial title');
    expect(screen.getByLabelText(/类型/)).toHaveValue('snow');
    expect(screen.getByLabelText(/发布时间/)).toHaveValue('2026-01-01T00:00');

    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: '恢复草稿' }));

    expect(screen.getByLabelText(/标题/)).toHaveValue('Draft title');
    expect(screen.getByLabelText(/类型/)).toHaveValue('storm');
    expect(screen.getByLabelText(/正文/)).toHaveValue('draft body');
  });

  it('shows a submit error when onSubmit throws', async () => {
    localStorage.removeItem(NEW_STORAGE_KEY);
    const { ProductEditor } = await importFreshEditor();
    const onSubmit = vi.fn(() => {
      throw new Error('boom');
    });
    const onClose = vi.fn();

    render(<ProductEditor open onClose={onClose} onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/标题/), 'T');
    await user.type(screen.getByLabelText(/类型/), 'Type');
    await user.type(screen.getByLabelText(/正文/), 'Body');
    await user.type(screen.getByLabelText(/发布时间/), '2026-01-01T00:00');
    await user.type(screen.getByLabelText(/有效开始时间/), '2026-01-01T00:00');
    await user.type(screen.getByLabelText(/有效结束时间/), '2026-01-02T00:00');

    await user.click(screen.getByRole('button', { name: '提交' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('提交失败：boom');
    expect(onClose).not.toHaveBeenCalled();
  });
});
