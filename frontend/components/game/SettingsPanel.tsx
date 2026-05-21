'use client';

import { useState } from 'react';
import { useLocale, useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { Modal } from '@/components/ui/Modal';
import { Button } from '@/components/ui/Button';

interface SettingsPanelProps {
  sessionId: string;
}

const FONT_SIZE_KEY = 'llm_rpg_font_size';
const BGM_VOLUME_KEY = 'llm_rpg_bgm_volume';

type FontSize = 'normal' | 'large';

export function SettingsPanel({ sessionId }: SettingsPanelProps) {
  const t = useTranslations('Game');
  const locale = useLocale();
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);

  const [fontSize, setFontSize] = useState<FontSize>(() => {
    if (typeof window === 'undefined') return 'normal';
    return (localStorage.getItem(FONT_SIZE_KEY) as FontSize) || 'normal';
  });

  const [bgmVolume, setBgmVolume] = useState(() => {
    if (typeof window === 'undefined') return 70;
    const stored = localStorage.getItem(BGM_VOLUME_KEY);
    return stored ? parseInt(stored, 10) : 70;
  });

  const handleFontSizeChange = (size: FontSize) => {
    setFontSize(size);
    localStorage.setItem(FONT_SIZE_KEY, size);
    document.documentElement.classList.toggle('text-lg-mode', size === 'large');
  };

  const handleVolumeChange = (value: number) => {
    setBgmVolume(value);
    localStorage.setItem(BGM_VOLUME_KEY, String(value));
  };

  const handleReturnToSaves = () => {
    setIsOpen(false);
    router.push('/saves');
  };

  const languageName = locale === 'zh' ? '中文' : 'English';

  return (
    <>
      <button
        onClick={() => setIsOpen(true)}
        className="min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 p-2 rounded-lg text-slate-600 hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 transition-colors"
        aria-label={t('settings')}
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
          />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      </button>

      <Modal
        isOpen={isOpen}
        onClose={() => setIsOpen(false)}
        title={t('settings')}
        size="md"
      >
        <div className="space-y-6">
          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-3">
              {t('settingsSound')}
            </h4>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-slate-600 dark:text-slate-400">
                  {t('settingsBgmVolume')}
                </span>
                <span className="text-xs text-slate-500 dark:text-slate-500 min-w-[40px] text-right">
                  {bgmVolume}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={bgmVolume}
                onChange={(e) => handleVolumeChange(parseInt(e.target.value, 10))}
                className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-indigo-600"
              />
            </div>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-3">
              {t('settingsLanguage')}
            </h4>
            <div className="flex items-center justify-between p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
              <span className="text-sm text-slate-600 dark:text-slate-400">
                {languageName}
              </span>
              <span className="text-xs text-slate-400 dark:text-slate-500">
                ({t('settingsLanguageReadonly')})
              </span>
            </div>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-3">
              {t('settingsDisplay')}
            </h4>
            <div className="flex gap-2">
              <button
                onClick={() => handleFontSizeChange('normal')}
                className={`flex-1 py-2 px-4 text-sm font-medium rounded-lg transition-colors ${
                  fontSize === 'normal'
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                }`}
              >
                {t('settingsFontNormal')}
              </button>
              <button
                onClick={() => handleFontSizeChange('large')}
                className={`flex-1 py-2 px-4 text-sm font-medium rounded-lg transition-colors ${
                  fontSize === 'large'
                    ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-300'
                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700'
                }`}
              >
                {t('settingsFontLarge')}
              </button>
            </div>
          </div>

          <div>
            <h4 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-3">
              {t('settingsSession')}
            </h4>
            <div className="space-y-3">
              <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">
                    {t('settingsSessionId')}
                  </span>
                  <span className="font-mono text-xs text-slate-600 dark:text-slate-300">
                    {sessionId.slice(0, 8)}...
                  </span>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={handleReturnToSaves}
                className="w-full"
              >
                <svg className="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
                  />
                </svg>
                {t('settingsReturnToSaves')}
              </Button>
            </div>
          </div>
        </div>
      </Modal>
    </>
  );
}
