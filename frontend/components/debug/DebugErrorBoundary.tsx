'use client';

import React, { Component, ErrorInfo, ReactNode } from 'react';
import { useTranslations } from 'next-intl';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

interface DebugErrorBoundaryProps {
  children: ReactNode;
  onRetry?: () => void;
  message?: string;
}

interface DebugErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class DebugErrorBoundaryInner extends Component<
  DebugErrorBoundaryProps & { t: (key: string) => string },
  DebugErrorBoundaryState
> {
  constructor(props: DebugErrorBoundaryProps & { t: (key: string) => string }) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): DebugErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Debug view error:', error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
    this.props.onRetry?.();
  };

  render() {
    const { hasError, error } = this.state;
    const { children, t, message } = this.props;

    if (hasError) {
      return (
        <Card className="p-6 bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800">
          <div className="flex items-start gap-3">
            <svg
              className="w-6 h-6 text-red-500 flex-shrink-0 mt-0.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-red-800 dark:text-red-300">
                {t('errorBoundary.title')}
              </h3>
              <p className="text-sm text-red-700 dark:text-red-400 mt-1">
                {message ?? error?.message ?? t('errorBoundary.defaultMessage')}
              </p>
              <div className="mt-4">
                <Button size="sm" variant="outline" onClick={this.handleRetry}>
                  {t('errorBoundary.retry')}
                </Button>
              </div>
            </div>
          </div>
        </Card>
      );
    }

    return children;
  }
}

export function DebugErrorBoundary({ children, onRetry, message }: DebugErrorBoundaryProps) {
  const t = useTranslations('Debug');

  return (
    <DebugErrorBoundaryInner t={t} onRetry={onRetry} message={message}>
      {children}
    </DebugErrorBoundaryInner>
  );
}
