import { useCallback, useEffect, useRef } from 'react';

function isFocusable(element: HTMLElement): boolean {
  if (element.matches('[disabled]')) return false;
  if (element.getAttribute('aria-hidden') === 'true') return false;

  const tabIndex = element.getAttribute('tabindex');
  if (tabIndex === '-1') return false;

  return true;
}

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  const selectors = [
    'a[href]',
    'area[href]',
    'button',
    'input',
    'select',
    'textarea',
    'iframe',
    'object',
    'embed',
    '[contenteditable="true"]',
    '[tabindex]',
  ];

  return Array.from(container.querySelectorAll<HTMLElement>(selectors.join(','))).filter(isFocusable);
}

function setInert(el: HTMLElement, inert: boolean) {
  (el as HTMLElement & { inert?: boolean }).inert = inert;
  if (inert) {
    el.setAttribute('inert', '');
  } else {
    el.removeAttribute('inert');
  }
}

type UseModalOptions = {
  open: boolean;
  modalRef: React.RefObject<HTMLElement | null>;
  initialFocusRef?: React.RefObject<HTMLElement | null>;
  onClose: () => void;
  appRootId?: string;
};

export function useModal({
  open,
  modalRef,
  initialFocusRef,
  onClose,
  appRootId = 'root',
}: UseModalOptions) {
  const onCloseRef = useRef(onClose);
  const previouslyFocusedElementRef = useRef<HTMLElement | null>(null);
  const appRootStateRef = useRef<{
    element: HTMLElement;
    ariaHidden: string | null;
    inertProperty: boolean;
    inertAttribute: boolean;
  } | null>(null);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const onOverlayMouseDown = useCallback((event: React.MouseEvent<HTMLElement>) => {
    if (event.target === event.currentTarget) onCloseRef.current();
  }, []);

  useEffect(() => {
    if (!open) return;

    previouslyFocusedElementRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const appRoot = document.getElementById(appRootId);
    if (appRoot) {
      appRootStateRef.current = {
        element: appRoot,
        ariaHidden: appRoot.getAttribute('aria-hidden'),
        inertProperty: Boolean((appRoot as HTMLElement & { inert?: boolean }).inert),
        inertAttribute: appRoot.hasAttribute('inert'),
      };

      appRoot.setAttribute('aria-hidden', 'true');
      setInert(appRoot, true);
    }

    const focusInitial = () => {
      const initialFocusElement = initialFocusRef?.current;
      if (initialFocusElement) {
        initialFocusElement.focus();
        return;
      }

      const modalElement = modalRef.current;
      if (!modalElement) return;

      const focusable = getFocusableElements(modalElement);
      focusable[0]?.focus();
    };

    focusInitial();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }

      if (event.key !== 'Tab') return;

      const modalElement = modalRef.current;
      if (!modalElement) return;

      const focusable = getFocusableElements(modalElement);
      if (focusable.length === 0) return;

      const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

      if (!activeElement || !modalElement.contains(activeElement)) {
        event.preventDefault();
        focusable[0]?.focus();
        return;
      }

      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;

      if (event.shiftKey) {
        if (activeElement === first) {
          event.preventDefault();
          last.focus();
        }
        return;
      }

      if (activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    const onFocusIn = (event: FocusEvent) => {
      const modalElement = modalRef.current;
      if (!modalElement) return;

      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      if (modalElement.contains(target)) return;

      const focusable = getFocusableElements(modalElement);
      focusable[0]?.focus();
    };

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('focusin', onFocusIn);

    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('focusin', onFocusIn);

      const appRootState = appRootStateRef.current;
      if (appRootState) {
        const { element, ariaHidden, inertProperty, inertAttribute } = appRootState;
        if (ariaHidden === null) {
          element.removeAttribute('aria-hidden');
        } else {
          element.setAttribute('aria-hidden', ariaHidden);
        }
        (element as HTMLElement & { inert?: boolean }).inert = inertProperty;
        if (inertAttribute) {
          element.setAttribute('inert', '');
        } else {
          element.removeAttribute('inert');
        }
        appRootStateRef.current = null;
      }

      const elementToRestore = previouslyFocusedElementRef.current;
      if (elementToRestore && document.contains(elementToRestore)) {
        elementToRestore.focus();
      }
      previouslyFocusedElementRef.current = null;
    };
  }, [appRootId, initialFocusRef, modalRef, open]);

  return { onOverlayMouseDown };
}
