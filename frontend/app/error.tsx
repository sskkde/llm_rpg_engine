'use client';

import { useEffect } from 'react';
import {useTranslations} from 'next-intl';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';

interface ErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
}

export default function RootError({ error, reset }: ErrorProps) {
  const t = useTranslations('Errors');

  useEffect(() => {
    console.error('Root error boundary caught:', error);
  }, [error]);

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
            {t('somethingWentWrong')}
          </h2>

          <p className="text-slate-600 dark:text-slate-400 mb-6">
            {t('unexpectedError')}
          </p>

          {error.digest && (
            <p className="text-xs text-slate-400 dark:text-slate-500 mb-4 font-mono">
              {t('errorId', {digest: error.digest})}
            </p>
          )}

          <div className="flex justify-center gap-3">
            <Button onClick={reset}>{t('tryAgain')}</Button>
            <Button variant="outline" onClick={() => window.location.reload()}>
              {t('refreshPage')}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
