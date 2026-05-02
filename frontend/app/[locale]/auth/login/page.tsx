'use client';

import {Link} from '@/i18n/navigation';
import {useTranslations} from 'next-intl';
import {Card} from '@/components/ui/Card';
import {LoginForm} from '@/components/auth/LoginForm';

export default function LoginPage() {
  const t = useTranslations('Auth');

  return (
    <div className="min-h-[calc(100vh-4rem)] flex items-center justify-center p-4 bg-slate-50 dark:bg-slate-900">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-slate-900 dark:text-slate-100">
            {t('loginTitle')}
          </h1>
          <p className="mt-2 text-slate-600 dark:text-slate-400">
            {t('loginToAccount')}
          </p>
        </div>

        <Card className="p-6">
          <LoginForm />
        </Card>

        <p className="mt-6 text-center text-sm text-slate-600 dark:text-slate-400">
          {t('noAccount')}{' '}
          <Link
            href="/auth/register"
            className="font-medium text-indigo-600 hover:text-indigo-500 dark:text-indigo-400"
          >
            {t('createAccount')}
          </Link>
        </p>
      </div>
    </div>
  );
}
