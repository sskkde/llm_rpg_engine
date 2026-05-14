'use client';

import React from 'react';
import { useTranslations } from 'next-intl';
import { Loading } from '@/components/ui/Loading';

interface DebugLoadingProps {
  size?: 'sm' | 'md' | 'lg';
}

export function DebugLoading({ size = 'md' }: DebugLoadingProps) {
  const t = useTranslations('Debug');

  return <Loading size={size} text={t('loadingDebugData')} />;
}
