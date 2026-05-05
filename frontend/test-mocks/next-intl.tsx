import React, {createContext, useContext} from 'react';
import zhMessages from '@/messages/zh.json';
import enMessages from '@/messages/en.json';

type Locale = 'zh' | 'en';
type MessageTree = Record<string, unknown>;

const defaultMessages: Record<Locale, MessageTree> = {
  zh: zhMessages,
  en: enMessages,
};

interface IntlContextValue {
  locale: Locale;
  messages: MessageTree;
}

const IntlContext = createContext<IntlContextValue>({
  locale: 'zh',
  messages: defaultMessages.zh,
});

interface NextIntlClientProviderProps {
  children: React.ReactNode;
  locale?: string;
  messages?: MessageTree;
}

function getNestedMessage(messages: MessageTree, path: string): string {
  const value = path.split('.').reduce<unknown>((current, part) => {
    if (current && typeof current === 'object' && part in current) {
      return (current as Record<string, unknown>)[part];
    }
    return undefined;
  }, messages);

  return typeof value === 'string' ? value : path;
}

function interpolate(message: string, values?: Record<string, string | number>): string {
  if (!values) return message;
  return Object.entries(values).reduce(
    (result, [key, value]) => result.replaceAll(`{${key}}`, String(value)),
    message
  );
}

export function NextIntlClientProvider({
  children,
  locale = 'zh',
  messages,
}: NextIntlClientProviderProps) {
  const safeLocale: Locale = locale === 'en' ? 'en' : 'zh';
  return (
    <IntlContext.Provider value={{locale: safeLocale, messages: messages ?? defaultMessages[safeLocale]}}>
      {children}
    </IntlContext.Provider>
  );
}

export function useLocale() {
  return useContext(IntlContext).locale;
}

export function useTranslations(namespace?: string) {
  const {messages} = useContext(IntlContext);
  return React.useCallback((key: string, values?: Record<string, string | number>) => {
    const path = namespace ? `${namespace}.${key}` : key;
    return interpolate(getNestedMessage(messages, path), values);
  }, [messages, namespace]);
}

export function useFormatter() {
  const {locale} = useContext(IntlContext);
  return {
    dateTime(value: Date | number | string, options?: Intl.DateTimeFormatOptions) {
      return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', options).format(new Date(value));
    },
    number(value: number, options?: Intl.NumberFormatOptions) {
      return new Intl.NumberFormat(locale === 'zh' ? 'zh-CN' : 'en-US', options).format(value);
    },
  };
}
