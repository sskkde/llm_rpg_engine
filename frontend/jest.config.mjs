import nextJest from 'next/jest.js';

const createJestConfig = nextJest({
  dir: './',
});

const customJestConfig = {
  setupFilesAfterEnv: ['<rootDir>/jest.setup.js'],
  testEnvironment: 'jest-environment-jsdom',
  testMatch: ['**/*.test.ts', '**/*.test.tsx'],
  moduleNameMapper: {
    '^next-intl$': '<rootDir>/test-mocks/next-intl.tsx',
    '^next-intl/navigation$': '<rootDir>/test-mocks/next-intl-navigation.tsx',
    '^next-intl/routing$': '<rootDir>/test-mocks/next-intl-routing.ts',
    '^@/(.*)$': '<rootDir>/$1',
  },
  transformIgnorePatterns: [
    '/node_modules/(?!(next-intl|use-intl)/)',
  ],
};

export default createJestConfig(customJestConfig);
