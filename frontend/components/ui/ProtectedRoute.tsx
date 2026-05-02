'use client';

import React from 'react';
import {useTranslations} from 'next-intl';
import {useAuth} from '@/hooks/useAuth';
import {Loading} from './Loading';
import {Button} from './Button';
import {Link} from '@/i18n/navigation';

interface ProtectedRouteProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  redirectTo?: string;
}

export function ProtectedRoute({
  children,
  fallback,
  redirectTo = '/auth/login',
}: ProtectedRouteProps) {
  const {isAuthenticated, isLoading} = useAuth();
  const t = useTranslations('ProtectedRoute');

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <Loading size="lg" text={t('loginMessage')} />
      </div>
    );
  }

  if (!isAuthenticated) {
    if (fallback) {
      return <>{fallback}</>;
    }

    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50 dark:bg-slate-900">
        <div className="max-w-md w-full text-center">
          <div className="w-16 h-16 bg-indigo-100 dark:bg-indigo-900/30 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg
              className="w-8 h-8 text-indigo-600 dark:text-indigo-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"
              />
            </svg>
          </div>

          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">
            {t('loginRequired')}
          </h2>

          <p className="text-slate-600 dark:text-slate-400 mb-6">
            {t('loginMessage')}
          </p>

          <div className="flex justify-center gap-3">
            <Link href={redirectTo}>
              <Button>{t('loginRequired')}</Button>
            </Link>
            <Link href="/auth/register">
              <Button variant="outline">{t('loginRequired')}</Button>
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

interface AdminRouteProps extends ProtectedRouteProps {
  children: React.ReactNode;
}

export function AdminRoute({children}: AdminRouteProps) {
  const {isAuthenticated, isLoading, user} = useAuth();
  const t = useTranslations('ProtectedRoute');

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
        <Loading size="lg" text={t('adminMessage')} />
      </div>
    );
  }

  if (!isAuthenticated) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50 dark:bg-slate-900">
        <div className="max-w-md w-full text-center">
          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">
            {t('loginRequired')}
          </h2>
          <p className="text-slate-600 dark:text-slate-400 mb-6">
            {t('adminMessage')}
          </p>
          <Link href="/auth/login">
            <Button>{t('loginRequired')}</Button>
          </Link>
        </div>
      </div>
    );
  }

  const isAdmin = user?.username === 'admin' || user?.email?.includes('admin');

  if (!isAdmin) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50 dark:bg-slate-900">
        <div className="max-w-md w-full text-center">
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
                d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"
              />
            </svg>
          </div>

          <h2 className="text-2xl font-bold text-slate-900 dark:text-slate-100 mb-2">
            {t('adminRequired')}
          </h2>

          <p className="text-slate-600 dark:text-slate-400 mb-6">
            {t('adminMessage')}
          </p>

          <Link href="/">
            <Button>{t('loginRequired')}</Button>
          </Link>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
