'use client';

import React, {useState, useSyncExternalStore} from 'react';
import {useTranslations} from 'next-intl';
import {useRouter} from '@/i18n/navigation';
import {useAuth} from '@/hooks/useAuth';
import {Input} from '@/components/ui/Input';
import {Button} from '@/components/ui/Button';
import {ErrorMessage} from '@/components/ui/ErrorMessage';
import {APIError} from '@/lib/api';

const subscribeToHydration = () => () => {};
const hydratedSnapshot = () => true;
const serverSnapshot = () => false;

export function RegisterForm() {
  const router = useRouter();
  const { register } = useAuth();
  const t = useTranslations('Auth');
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const isHydrated = useSyncExternalStore(subscribeToHydration, hydratedSnapshot, serverSnapshot);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!isHydrated) {
      return;
    }

    if (!username.trim() || !password) {
      setError(t('usernameAndPasswordRequired'));
      return;
    }

    if (password.length < 8) {
      setError(t('passwordMinLength'));
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      await register(username, password, email || undefined);
      router.push('/auth/login?registered=1');
    } catch (err) {
      if (err instanceof APIError) {
        if (err.status === 409) {
          setError(t('usernameExists'));
        } else if (err.status === 422) {
          setError(err.detail || t('invalidInput'));
        } else {
          setError(err.detail || t('registrationError'));
        }
      } else {
        setError(t('unexpectedError'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form method="post" onSubmit={handleSubmit} className="space-y-4">
      {error && (
        <ErrorMessage
          message={error}
          variant="card"
          onDismiss={() => setError(null)}
          data-testid="register-error"
        />
      )}

      <Input
        id="username"
        name="username"
        type="text"
        label={t('username')}
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder={t('chooseUsername')}
        autoComplete="username"
        required
        disabled={!isHydrated || isLoading}
        data-testid="register-username-input"
      />

      <Input
        id="email"
        name="email"
        type="email"
        label={t('emailOptional')}
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder={t('enterEmail')}
        autoComplete="email"
        disabled={!isHydrated || isLoading}
        data-testid="register-email-input"
      />

      <Input
        id="password"
        name="password"
        type="password"
        label={t('password')}
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder={t('createPassword')}
        autoComplete="new-password"
        required
        disabled={!isHydrated || isLoading}
        helperText={t('passwordHelperText')}
        data-testid="register-password-input"
      />

      <Button
        type="submit"
        variant="primary"
        size="lg"
        isLoading={isLoading}
        disabled={!isHydrated || isLoading}
        className="w-full"
        data-testid="register-submit"
      >
        {t('createAccount')}
      </Button>
    </form>
  );
}
