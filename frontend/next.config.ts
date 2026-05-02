import type {NextConfig} from 'next';
import path from 'node:path';

const backendApiUrl = process.env.BACKEND_API_URL || 'http://127.0.0.1:8000';
const apiProxyPrefixes = [
  'auth',
  'saves',
  'sessions',
  'world',
  'game',
  'streaming',
  'combat',
  'admin',
  'debug',
  'media',
  'dev',
];

const nextConfig: NextConfig = {
  async rewrites() {
    return apiProxyPrefixes.map((prefix) => ({
      source: `/${prefix}/:path*`,
      destination: `${backendApiUrl}/${prefix}/:path*`,
    }));
  },
  allowedDevOrigins: ['127.0.0.1'],
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
