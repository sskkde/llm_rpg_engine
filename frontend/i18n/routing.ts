import {defineRouting} from 'next-intl/routing';

export const routing = defineRouting({
  // A list of all locales that are supported
  locales: ['zh', 'en'],

  // Used when no locale matches
  defaultLocale: 'zh',
  localeDetection: false,

  localePrefix: {
    mode: 'always',
    prefixes: {
      zh: '/zh',
      en: '/en',
    },
  },
});
