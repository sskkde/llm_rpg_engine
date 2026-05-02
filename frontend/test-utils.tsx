import React from 'react';
import {render, type RenderOptions} from '@testing-library/react';
import {NextIntlClientProvider} from 'next-intl';
import zhMessages from '@/messages/zh.json';
import enMessages from '@/messages/en.json';

const messages = {
  zh: zhMessages,
  en: enMessages,
};

type TestLocale = keyof typeof messages;

type RenderWithIntlOptions = RenderOptions & {
  locale?: TestLocale;
};

export function renderWithIntl(
  ui: React.ReactElement,
  {locale = 'zh', ...renderOptions}: RenderWithIntlOptions = {}
) {
  return render(
    <NextIntlClientProvider locale={locale} messages={messages[locale]}>
      {ui}
    </NextIntlClientProvider>,
    renderOptions
  );
}

export {messages};
