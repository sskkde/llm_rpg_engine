'use client';

import {useTranslations} from 'next-intl';
import {useRouter} from '@/i18n/navigation';
import { ProtectedRoute } from '@/components/ui/ProtectedRoute';
import { Button } from '@/components/ui/Button';

export default function GamePage() {
  return (
    <ProtectedRoute>
      <GameContent />
    </ProtectedRoute>
  );
}

function GameContent() {
  const router = useRouter();
  const t = useTranslations('Game');

  return (
    <div className="max-w-4xl mx-auto px-4 py-12 text-center">
      <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-4">
        {t('gameSessions')}
      </h1>
      <p className="text-slate-600 dark:text-slate-400 mb-8">
        {t('loadSessionPrompt')}
      </p>
      <Button onClick={() => router.push('/saves')}>
        {t('goToSaves')}
      </Button>
    </div>
  );
}
