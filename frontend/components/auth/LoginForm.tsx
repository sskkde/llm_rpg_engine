'use client';

import React, {useState} from 'react';
import {useRouter} from '@/i18n/navigation';
import {useTranslations} from 'next-intl';
import {useAuth} from '@/hooks/useAuth';
import {Input} from '@/components/ui/Input';
import {Button} from '@/components/ui/Button';
import {ErrorMessage} from '@/components/ui/ErrorMessage';
import {APIError} from '@/lib/api';

export function LoginForm() {
  const router = useRouter();
  const {login} = useAuth();
  const t = useTranslations('Auth');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!username.trim() || !password) {
      setError(t('usernameRequired') + ' / ' + t('passwordRequired'));
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await login(username, password);
      router.push('/saves');
    } catch (err) {
      if (err instanceof APIError) {
        if (err.status === 401) {
          setError(t('invalidCredentials'));
        } else if (err.status === 422) {
          setError(err.detail || t('invalidCredentials'));
        } else {
          setError(err.detail || t('invalidCredentials'));
        }
      } else {
        setError(t('invalidCredentials'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <ErrorMessage
          message={error}
          variant="card"
          onDismiss={() => setError(null)}
          data-testid="login-error"
        />
      )}

      <Input
        id="username"
        name="username"
        type="text"
        label={t('username')}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder={t('username')}
        autoComplete="username"
        required
        disabled={isLoading}
        data-testid="username-input"
      />

      <Input
        id="password"
        name="password"
        type="password"
        label={t('password')}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder={t('password')}
        autoComplete="current-password"
        required
        disabled={isLoading}
        data-testid="password-input"
      />

      <Button
        type="submit"
        variant="primary"
        size="lg"
        isLoading={isLoading}
        disabled={isLoading}
        className="w-full"
        data-testid="login-submit"
      >
        {t('loginButton')}
      </Button>
    </form>
  );
}
