import type { ReactNode } from 'react';
import React from 'react';

import ErrorFallback from './ErrorFallback';

type FallbackRender = (args: {
  error: unknown;
  resetErrorBoundary: () => void;
}) => ReactNode;

type Props = {
  children: ReactNode;
  onError?: (error: unknown, componentStack: string) => void;
  onReset?: () => void;
  resetKeys?: unknown[];
  fallback?: ReactNode;
  fallbackRender?: FallbackRender;
};

type State = {
  error: unknown | null;
};

export default class ErrorBoundary extends React.Component<Props, State> {
  public state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo): void {
    this.props.onError?.(error, info.componentStack ?? '');
  }

  componentDidUpdate(prevProps: Props): void {
    const prevKeys = prevProps.resetKeys ?? [];
    const nextKeys = this.props.resetKeys ?? [];

    if (!this.state.error) return;

    if (prevKeys.length !== nextKeys.length) {
      this.resetErrorBoundary();
      return;
    }

    const changed = nextKeys.some((key, index) => !Object.is(key, prevKeys[index]));
    if (changed) this.resetErrorBoundary();
  }

  private resetErrorBoundary = (): void => {
    this.props.onReset?.();
    this.setState({ error: null });
  };

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallbackRender) {
      return this.props.fallbackRender({
        error,
        resetErrorBoundary: this.resetErrorBoundary,
      });
    }

    if (this.props.fallback) return this.props.fallback;

    return <ErrorFallback error={error} onRetry={this.resetErrorBoundary} />;
  }
}
