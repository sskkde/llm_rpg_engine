'use client';

import React, {useState} from 'react';
import {Link, usePathname, useRouter} from '@/i18n/navigation';
import {useLocale, useTranslations} from 'next-intl';
import {useAuth} from '@/hooks/useAuth';
import {Button} from '@/components/ui/Button';
import {Badge} from '@/components/ui/Badge';

export function Navigation() {
  const {user, isAuthenticated, isLoading, logout} = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const locale = useLocale();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const t = useTranslations('Navigation');
  const tLang = useTranslations('LanguageSwitcher');

  const isAdmin = user?.is_admin === true;

  const navLinks = [
    {href: '/', label: t('home'), auth: false},
    {href: '/game', label: t('game'), auth: true},
    {href: '/saves', label: t('saves'), auth: true},
    ...(isAdmin
      ? [
          {href: '/admin', label: t('admin'), auth: true},
          {href: '/debug', label: t('debug'), auth: true},
        ]
      : []),
  ];

  const isActive = (href: string) => {
    if (href === '/') return pathname === href;
    return pathname.startsWith(href);
  };

  const switchLocale = (newLocale: string) => {
    router.replace(pathname, {locale: newLocale});
  };

  return (
    <nav className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-800 sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between h-16">
          <div className="flex items-center">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center">
                <svg
                  className="w-5 h-5 text-white"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253"
                  />
                </svg>
              </div>
              <span className="text-xl font-bold bg-gradient-to-r from-indigo-600 to-purple-600 bg-clip-text text-transparent hidden sm:block">
                RPG Engine
              </span>
            </Link>

            <div className="hidden md:flex items-center ml-8 gap-1">
              {navLinks
                .filter((link) => !link.auth || isAuthenticated)
                .map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    className={`
                      px-3 py-2 rounded-lg text-sm font-medium transition-colors
                      ${
                        isActive(link.href)
                          ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400'
                          : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                      }
                    `}
                  >
                    {link.label}
                    {link.label === t('admin') && (
                      <Badge variant="warning" size="sm" className="ml-2">
                        Admin
                      </Badge>
                    )}
                  </Link>
                ))}
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-1" data-testid="language-switcher">
              <button
                onClick={() => switchLocale('zh')}
                className={`min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:px-2 sm:py-1 text-xs font-medium rounded ${
                  locale === 'zh'
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                }`}
                data-testid="language-switcher-zh"
              >
                {tLang('zh')}
              </button>
              <button
                onClick={() => switchLocale('en')}
                className={`min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:px-2 sm:py-1 text-xs font-medium rounded ${
                  locale === 'en'
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                    : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                }`}
                data-testid="language-switcher-en"
              >
                {tLang('en')}
              </button>
            </div>

            {isLoading ? (
              <div className="w-20 h-8 bg-slate-200 dark:bg-slate-800 rounded-lg animate-pulse" />
            ) : isAuthenticated ? (
              <>
                <div className="hidden sm:flex items-center gap-2">
                  <div className="w-8 h-8 bg-gradient-to-br from-emerald-400 to-cyan-500 rounded-full flex items-center justify-center">
                    <span className="text-sm font-bold text-white">
                      {user?.username?.charAt(0).toUpperCase() || 'U'}
                    </span>
                  </div>
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                    {user?.username}
                  </span>
                </div>
                <Button variant="ghost" size="sm" onClick={logout}>
                  <svg
                    className="w-4 h-4 mr-1"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"
                    />
                  </svg>
                  {t('logout')}
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-2">
                <Link href="/auth/login" className="hidden sm:block">
                  <Button variant="ghost" size="sm">
                    {t('login')}
                  </Button>
                </Link>
                <Link href="/auth/register">
                  <Button size="sm">{t('register')}</Button>
                </Link>
              </div>
            )}

            <button
              className="md:hidden min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:p-2 rounded-lg text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              aria-label="Toggle menu"
            >
              {mobileMenuOpen ? (
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              ) : (
                <svg
                  className="w-6 h-6"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 6h16M4 12h16M4 18h16"
                  />
                </svg>
              )}
            </button>
          </div>
        </div>

        {mobileMenuOpen && (
          <div className="md:hidden py-3 border-t border-slate-200 dark:border-slate-800">
            <div className="flex flex-col gap-1">
              <div className="flex items-center gap-2 px-3 py-2" data-testid="language-switcher-mobile">
                <span className="text-sm font-medium text-slate-600 dark:text-slate-400">
                  {tLang('label')}:
                </span>
                <button
                  onClick={() => switchLocale('zh')}
                  className={`min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:px-2 sm:py-1 text-xs font-medium rounded ${
                    locale === 'zh'
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                  }`}
                  data-testid="language-switcher-zh"
                >
                  {tLang('zh')}
                </button>
                <button
                  onClick={() => switchLocale('en')}
                  className={`min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:px-2 sm:py-1 text-xs font-medium rounded ${
                    locale === 'en'
                      ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                  }`}
                  data-testid="language-switcher-en"
                >
                  {tLang('en')}
                </button>
              </div>

              {navLinks
                .filter((link) => !link.auth || isAuthenticated)
                .map((link) => (
                  <Link
                    key={link.href}
                    href={link.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={`
                      px-3 py-2 rounded-lg text-sm font-medium transition-colors
                      ${
                        isActive(link.href)
                          ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-900/30 dark:text-indigo-400'
                          : 'text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800'
                      }
                    `}
                  >
                    {link.label}
                  </Link>
                ))}
              {!isAuthenticated && (
                <>
                  <Link
                    href="/auth/login"
                    onClick={() => setMobileMenuOpen(false)}
                    className="px-3 py-2 rounded-lg text-sm font-medium text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
                  >
                    {t('login')}
                  </Link>
                  <Link
                    href="/auth/register"
                    onClick={() => setMobileMenuOpen(false)}
                    className="px-3 py-2 rounded-lg text-sm font-medium text-indigo-600 hover:bg-indigo-50 dark:text-indigo-400 dark:hover:bg-indigo-900/30"
                  >
                    {t('register')}
                  </Link>
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
