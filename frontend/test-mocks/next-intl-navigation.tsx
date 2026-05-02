import React from 'react';

type LinkProps = React.AnchorHTMLAttributes<HTMLAnchorElement> & {
  href: string;
  locale?: string;
};

function withLocale(href: string, locale?: string) {
  if (!locale || href.startsWith(`/${locale}`) || href.startsWith('http')) return href;
  return `/${locale}${href.startsWith('/') ? href : `/${href}`}`;
}

export function createNavigation() {
  return {
    Link({href, locale, children, ...props}: LinkProps) {
      return (
        <a href={withLocale(href, locale)} {...props}>
          {children}
        </a>
      );
    },
    redirect() {
      return undefined;
    },
    usePathname() {
      return '/';
    },
    useRouter() {
      return {
        push() {
          return undefined;
        },
        replace() {
          return undefined;
        },
      };
    },
    getPathname({href, locale}: {href: string; locale?: string}) {
      return withLocale(href, locale);
    },
  };
}
