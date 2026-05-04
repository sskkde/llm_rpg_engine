'use client';

import React, {useCallback, useEffect, useState} from 'react';
import {useTranslations} from 'next-intl';
import {Button} from '@/components/ui/Button';
import {Loading} from '@/components/ui/Loading';
import {ErrorMessage} from '@/components/ui/ErrorMessage';
import {getSystemSettings, updateSystemSettings} from '@/lib/api';
import type {SystemSettings, SystemSettingsUpdateRequest} from '@/types/api';

export function SystemSettingsPanel() {
  const t = useTranslations('Admin');
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  
  const [providerMode, setProviderMode] = useState<'auto' | 'openai' | 'mock'>('auto');
  const [defaultModel, setDefaultModel] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [maxTokens, setMaxTokens] = useState(2000);
  const [registrationEnabled, setRegistrationEnabled] = useState(true);
  const [maintenanceMode, setMaintenanceMode] = useState(false);
  const [debugEnabled, setDebugEnabled] = useState(true);
  const [secretAction, setSecretAction] = useState<'keep' | 'set' | 'clear'>('keep');
  const [secretValue, setSecretValue] = useState('');

  const loadSettings = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getSystemSettings();
      setSettings(data);
      setProviderMode(data.llm.provider_mode);
      setDefaultModel(data.llm.default_model || '');
      setTemperature(data.llm.temperature);
      setMaxTokens(data.llm.max_tokens);
      setRegistrationEnabled(data.ops.registration_enabled);
      setMaintenanceMode(data.ops.maintenance_mode);
      setDebugEnabled(data.ops.debug_enabled);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        setError(t('failedToLoad'));
      }
    } finally {
      setIsLoading(false);
    }
  }, [t]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadSettings();
  }, [loadSettings]);

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);
    
    try {
      const updateData: SystemSettingsUpdateRequest = {
        llm: {
          provider_mode: providerMode,
          default_model: defaultModel || undefined,
          temperature,
          max_tokens: maxTokens,
          openai_api_key: secretAction === 'keep' 
            ? {action: 'keep'}
            : secretAction === 'set'
              ? {action: 'set', value: secretValue}
              : {action: 'clear'},
        },
        ops: {
          registration_enabled: registrationEnabled,
          maintenance_mode: maintenanceMode,
          debug_enabled: debugEnabled,
        },
      };
      
      const result = await updateSystemSettings(updateData);
      setSettings(result);
      setSecretAction('keep');
      setSecretValue('');
      setSuccessMessage(t('settingsSaved'));
    } catch (err: unknown) {
      const detail = (err as { detail?: string })?.detail;
      setError(detail || t('failedToUpdate'));
    } finally {
      setIsSaving(false);
    }
  };

  if (isLoading) return <Loading size="md" text={t('loadingSettings')} />;
  if (error) return <ErrorMessage message={error} variant="card" onRetry={loadSettings} />;
  if (!settings) return null;

  return (
    <div className="space-y-6">
      {successMessage && (
        <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
          <p className="text-green-800 dark:text-green-200">{successMessage}</p>
        </div>
      )}

      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">{t('llmSettings')}</h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('providerMode')}
            </label>
            <select
              value={providerMode}
              onChange={(e) => setProviderMode(e.target.value as 'auto' | 'openai' | 'mock')}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            >
              <option value="auto">{t('auto')}</option>
              <option value="openai">{t('openai')}</option>
              <option value="mock">{t('mock')}</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('defaultModel')}
            </label>
            <input
              type="text"
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              placeholder="gpt-4"
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('temperature')}
            </label>
            <input
              type="number"
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              min={0}
              max={2}
              step={0.1}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('maxTokens')}
            </label>
            <input
              type="number"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value))}
              min={1}
              max={8000}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          </div>
        </div>

        <div className="mt-4">
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
            {t('openaiApiKey')}
          </label>
          <div className="text-sm text-slate-600 dark:text-slate-400 mb-2">
            {settings.llm.openai_api_key.configured ? (
              <span>{t('keyConfigured')} (****{settings.llm.openai_api_key.last4})</span>
            ) : (
              <span>{t('keyNotConfigured')}</span>
            )}
          </div>
          
          <div className="flex gap-2 mb-2">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="secretAction"
                value="keep"
                checked={secretAction === 'keep'}
                onChange={() => setSecretAction('keep')}
              />
              <span className="text-sm">{t('keepCurrent')}</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="secretAction"
                value="set"
                checked={secretAction === 'set'}
                onChange={() => setSecretAction('set')}
              />
              <span className="text-sm">{t('setNewKey')}</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="secretAction"
                value="clear"
                checked={secretAction === 'clear'}
                onChange={() => setSecretAction('clear')}
              />
              <span className="text-sm">{t('clearKey')}</span>
            </label>
          </div>
          
          {secretAction === 'set' && (
            <input
              type="password"
              value={secretValue}
              onChange={(e) => setSecretValue(e.target.value)}
              placeholder={t('enterNewKey')}
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
          )}
        </div>
      </div>

      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">{t('opsSettings')}</h3>
        
        <div className="space-y-3">
          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={registrationEnabled}
              onChange={(e) => setRegistrationEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">{t('registrationEnabled')}</span>
          </label>

          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={maintenanceMode}
              onChange={(e) => setMaintenanceMode(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">{t('maintenanceMode')}</span>
          </label>

          <label className="flex items-center gap-3">
            <input
              type="checkbox"
              checked={debugEnabled}
              onChange={(e) => setDebugEnabled(e.target.checked)}
              className="h-4 w-4 rounded border-slate-300"
            />
            <span className="text-sm text-slate-700 dark:text-slate-300">{t('debugEnabled')}</span>
          </label>
        </div>
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={isSaving}>
          {isSaving ? t('saving') : t('saveSettings')}
        </Button>
      </div>
    </div>
  );
}
