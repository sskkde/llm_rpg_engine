'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import {useTranslations} from 'next-intl';
import { Button } from './Button';
import { Card } from './Card';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
  labels?: {
    title: string;
    description: string;
    stackTrace: string;
    tryAgain: string;
    refreshPage: string;
  };
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundaryCore extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    this.props.onReset?.();
  };

  public render() {
    const labels = this.props.labels ?? {
      title: '出现问题',
      description: '应用程序发生意外错误。请尝试刷新页面，如果问题持续存在请联系支持。',
      stackTrace: '堆栈跟踪',
      tryAgain: '重试',
      refreshPage: '刷新页面',
    };

    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50 dark:bg-slate-900">
          <Card className="max-w-lg w-full" padding="lg">
            <div className="text-center">
              <div className="w-16 h-16 bg-red-100 dark:bg-red-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
                <svg
                  className="w-8 h-8 text-red-600 dark:text-red-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                  />
                </svg>
              </div>

              <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">
                {labels.title}
              </h2>

              <p className="text-slate-600 dark:text-slate-400 mb-6">
                {labels.description}
              </p>

              {this.state.error && (
                <div className="mb-6 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg text-left overflow-auto">
                  <p className="text-sm font-mono text-red-800 dark:text-red-300">
                    {this.state.error.toString()}
                  </p>
                  {this.state.errorInfo && (
                    <details className="mt-2">
                      <summary className="text-xs text-red-600 dark:text-red-400 cursor-pointer">
                        {labels.stackTrace}
                      </summary>
                      <pre className="mt-2 text-xs text-red-700 dark:text-red-400 overflow-auto whitespace-pre-wrap">
                        {this.state.errorInfo.componentStack}
                      </pre>
                    </details>
                  )}
                </div>
              )}

              <div className="flex justify-center gap-3">
                <Button onClick={this.handleReset} variant="primary">
                  {labels.tryAgain}
                </Button>
                <Button
                  onClick={() => window.location.reload()}
                  variant="outline"
                >
                  {labels.refreshPage}
                </Button>
              </div>
            </div>
          </Card>
        </div>
      );
    }

    return this.props.children;
  }
}

export function ErrorBoundary(props: Omit<Props, 'labels'>) {
  const t = useTranslations('Errors');

  return (
    <ErrorBoundaryCore
      {...props}
      labels={{
        title: t('somethingWentWrong'),
        description: t('unexpectedError'),
        stackTrace: t('stackTrace'),
        tryAgain: t('tryAgain'),
        refreshPage: t('refreshPage'),
      }}
    />
  );
}

export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  fallback?: ReactNode
) {
  return function WithErrorBoundaryWrapper(props: P) {
    return (
      <ErrorBoundary fallback={fallback}>
        <Component {...props} />
      </ErrorBoundary>
    );
  };
}
