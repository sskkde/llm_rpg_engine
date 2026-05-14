'use client';

import { useTranslations } from 'next-intl';

interface AssetFallbackProps {
  variant: 'loading' | 'error' | 'empty';
  message?: string;
  onRetry?: () => void;
}

export function AssetFallback({ variant, message, onRetry }: AssetFallbackProps) {
  const t = useTranslations('Assets');

  if (variant === 'loading') {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-400">
        <span className="inline-block w-4 h-4 border-2 border-slate-300 border-t-transparent rounded-full animate-spin" />
        <span>{message || t('loading')}</span>
      </div>
    );
  }

  if (variant === 'error') {
    return (
      <div className="flex flex-col items-center gap-2 p-4 text-sm text-red-500">
        <span>⚠️</span>
        <span>{message || t('failed')}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-3 py-1 text-xs rounded bg-red-50 dark:bg-red-900/20 text-red-600 hover:bg-red-100 dark:hover:bg-red-900/40 transition-colors"
          >
            {t('retry')}
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 text-sm text-slate-400">
      <span>{message || t('empty')}</span>
    </div>
  );
}
