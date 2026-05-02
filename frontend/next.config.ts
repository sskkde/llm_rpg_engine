import type {NextConfig} from 'next';
import path from 'node:path';

const nextConfig: NextConfig = {
  webpack(config, {dir}) {
    config.resolve ??= {};
    config.resolve.alias ??= {};
    config.resolve.alias['next-intl/config'] = path.resolve(dir, 'i18n/request.ts');
    return config;
  },
  turbopack: {
    resolveAlias: {
      'next-intl/config': './i18n/request.ts',
    },
  },
};

export default nextConfig;
