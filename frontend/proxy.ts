import createMiddleware from 'next-intl/middleware';
import {routing} from './i18n/routing';

export default createMiddleware(routing);

export const config = {
  // Match all pathnames except for
  // - … if they start with a backend API prefix, `/api`, `/trpc`, `/_next` or `/_vercel`
  // - … the ones containing a dot (e.g. `favicon.ico`)
  matcher:
    '/((?!auth|saves|sessions|world|game|streaming|combat|admin|debug|media|dev|api|trpc|_next|_vercel|.*\\..*).*)'
};
