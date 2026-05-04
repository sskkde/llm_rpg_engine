'use client';

import React from 'react';
import {useTranslations} from 'next-intl';

interface ErrorMessageProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
  variant?: 'inline' | 'banner' | 'card';
}

export function ErrorMessage({
  title,
  message,
  onRetry,
  onDismiss,
  variant = 'inline',
  className = '',
  ...props
}: ErrorMessageProps) {
  const t = useTranslations('Common');
  const displayTitle = title ?? t('error');
  const icon = (
    <svg
      className="w-5 h-5 text-red-500"
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
  );

  if (variant === 'banner') {
    return (
      <div
        className={`
          fixed top-0 left-0 right-0 z-50
          bg-red-50 dark:bg-red-900/20 border-b border-red-200 dark:border-red-800
          px-4 py-3
          ${className}
        `}
        {...props}
      >
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            {icon}
            <div>
              <h4 className="text-sm font-semibold text-red-800 dark:text-red-300">{displayTitle}</h4>
              <p className="text-sm text-red-700 dark:text-red-400">{message}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {onRetry && (
              <button
                onClick={onRetry}
                className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 underline hover:text-red-800 dark:hover:text-red-300"
              >
                {t('retry')}
              </button>
            )}
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 flex items-center justify-center text-red-500 hover:text-red-700 dark:hover:text-red-300"
                aria-label={t('dismissError')}
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (variant === 'card') {
    return (
      <div
        className={`
          bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800
          rounded-lg p-4
          ${className}
        `}
        {...props}
      >
        <div className="flex items-start gap-3">
          <div className="flex-shrink-0 mt-0.5">{icon}</div>
          <div className="flex-1 min-w-0">
            <h4 className="text-sm font-semibold text-red-800 dark:text-red-300">{displayTitle}</h4>
            <p className="text-sm text-red-700 dark:text-red-400 mt-1">{message}</p>
          </div>
        </div>
        {(onRetry || onDismiss) && (
          <div className="flex items-center gap-3 mt-3 pt-3 border-t border-red-200 dark:border-red-800">
            {onRetry && (
              <button
                onClick={onRetry}
                className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 text-sm font-medium text-red-700 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
              >
                {t('retry')}
              </button>
            )}
            {onDismiss && (
              <button
                onClick={onDismiss}
                className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 text-sm text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
              >
                {t('dismiss')}
              </button>
            )}
          </div>
        )}
      </div>
    );
  }

  // Inline variant (default)
  return (
    <div
      className={`
        flex items-center gap-2 text-sm text-red-600 dark:text-red-400
        ${className}
      `}
      {...props}
    >
      {icon}
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 text-sm font-medium text-red-700 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
        >
          {t('retry')}
        </button>
      )}
    </div>
  );
}
