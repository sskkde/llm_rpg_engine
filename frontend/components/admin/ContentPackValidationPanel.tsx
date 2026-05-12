'use client';

import {useState} from 'react';
import {useTranslations} from 'next-intl';
import {Button} from '@/components/ui/Button';
import {validateContentPack, importContentPack} from '@/lib/api/adminContent';
import type {
  ContentPackValidateResponse,
  ContentPackImportResponse,
  ContentPackValidationIssue,
} from '@/types/api';

export function ContentPackValidationPanel() {
  const t = useTranslations('Admin');
  const [path, setPath] = useState('');
  const [isValidating, setIsValidating] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [validationResult, setValidationResult] = useState<ContentPackValidateResponse | null>(null);
  const [importResult, setImportResult] = useState<ContentPackImportResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showImportConfirm, setShowImportConfirm] = useState(false);

  const handleValidate = async () => {
    if (!path.trim()) {
      setError(t('pathRequired'));
      return;
    }

    setIsValidating(true);
    setError(null);
    setValidationResult(null);
    setImportResult(null);

    try {
      const result = await validateContentPack(path);
      setValidationResult(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('validationFailed'));
      }
    } finally {
      setIsValidating(false);
    }
  };

  const handleDryRun = async () => {
    if (!path.trim()) {
      setError(t('pathRequired'));
      return;
    }

    setIsImporting(true);
    setError(null);
    setImportResult(null);

    try {
      const result = await importContentPack(path, true);
      setImportResult(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('importFailed'));
      }
    } finally {
      setIsImporting(false);
    }
  };

  const handleImport = async () => {
    if (!path.trim()) {
      setError(t('pathRequired'));
      return;
    }

    setIsImporting(true);
    setError(null);
    setShowImportConfirm(false);

    try {
      const result = await importContentPack(path, false);
      setImportResult(result);
    } catch (err: unknown) {
      const status = (err as { status?: number })?.status;
      if (status === 401 || status === 403) {
        setError(t('adminRequired'));
      } else {
        const detail = (err as { detail?: string })?.detail;
        setError(detail || t('importFailed'));
      }
    } finally {
      setIsImporting(false);
    }
  };

  const renderIssues = (issues: ContentPackValidationIssue[]) => {
    if (issues.length === 0) return null;

    return (
      <div className="mt-4 space-y-2">
        {issues.map((issue, index) => (
          <div
            key={index}
            className={`p-3 rounded-lg text-sm ${
              issue.severity === 'error'
                ? 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
                : 'bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800'
            }`}
          >
            <div className="flex items-start gap-2">
              <span className={`font-medium ${
                issue.severity === 'error'
                  ? 'text-red-800 dark:text-red-200'
                  : 'text-yellow-800 dark:text-yellow-200'
              }`}>
                [{issue.severity.toUpperCase()}]
              </span>
              <span className={
                issue.severity === 'error'
                  ? 'text-red-700 dark:text-red-300'
                  : 'text-yellow-700 dark:text-yellow-300'
              }>
                {issue.message}
              </span>
            </div>
            <div className={`text-xs mt-1 ${
              issue.severity === 'error'
                ? 'text-red-600 dark:text-red-400'
                : 'text-yellow-600 dark:text-yellow-400'
            }`}>
              {t('path')}: {issue.path} | {t('code')}: {issue.code}
            </div>
          </div>
        ))}
      </div>
    );
  };

  const renderImportResult = (result: ContentPackImportResponse) => {
    return (
      <div className={`mt-4 p-4 rounded-lg ${
        result.success
          ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
          : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
      }`}>
        <h4 className={`font-semibold mb-2 ${
          result.success
            ? 'text-green-800 dark:text-green-200'
            : 'text-red-800 dark:text-red-200'
        }`}>
          {result.dry_run ? t('dryRunResult') : (result.success ? t('importSuccess') : t('importFailed'))}
        </h4>

        {result.pack_id && (
          <p className="text-sm text-slate-700 dark:text-slate-300">
            {t('packId')}: {result.pack_id}
          </p>
        )}
        {result.pack_name && (
          <p className="text-sm text-slate-700 dark:text-slate-300">
            {t('packName')}: {result.pack_name}
          </p>
        )}

        <div className="mt-2 text-sm">
          <p className="text-slate-700 dark:text-slate-300">
            {t('importedCount')}: {result.imported_count}
          </p>
          <p className="text-slate-700 dark:text-slate-300">
            {t('factionsImported')}: {result.factions_imported}
          </p>
          <p className="text-slate-700 dark:text-slate-300">
            {t('plotBeatsImported')}: {result.plot_beats_imported}
          </p>
        </div>

        {result.errors.length > 0 && (
          <div className="mt-3">
            <p className="font-medium text-red-800 dark:text-red-200">{t('errors')}:</p>
            <ul className="list-disc list-inside text-sm text-red-700 dark:text-red-300">
              {result.errors.map((err, i) => (
                <li key={i}>{err}</li>
              ))}
            </ul>
          </div>
        )}

        {result.warnings.length > 0 && (
          <div className="mt-3">
            <p className="font-medium text-yellow-800 dark:text-yellow-200">{t('warnings')}:</p>
            <ul className="list-disc list-inside text-sm text-yellow-700 dark:text-yellow-300">
              {result.warnings.map((warn, i) => (
                <li key={i}>{warn}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold text-slate-900 dark:text-slate-100">
        {t('contentPackValidation')}
      </h2>

      <div className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6">
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1">
              {t('contentPackPath')}
            </label>
            <input
              type="text"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder="content_packs/qinglan_xianxia"
              className="w-full px-3 py-2 bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-600 rounded-lg text-sm"
            />
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              {t('contentPackPathHelp')}
            </p>
          </div>

          {error && (
            <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
              <p className="text-red-800 dark:text-red-200">{error}</p>
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <Button onClick={handleValidate} disabled={isValidating || isImporting}>
              {isValidating ? t('validating') : t('validate')}
            </Button>
            <Button
              variant="secondary"
              onClick={handleDryRun}
              disabled={isValidating || isImporting || !validationResult?.is_valid}
            >
              {isImporting ? t('importing') : t('dryRunImport')}
            </Button>
            <Button
              variant="danger"
              onClick={() => setShowImportConfirm(true)}
              disabled={isValidating || isImporting || !validationResult?.is_valid}
            >
              {t('import')}
            </Button>
          </div>
        </div>

        {validationResult && (
          <div className={`mt-4 p-4 rounded-lg ${
            validationResult.is_valid
              ? 'bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800'
              : 'bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800'
          }`}>
            <h4 className={`font-semibold mb-2 ${
              validationResult.is_valid
                ? 'text-green-800 dark:text-green-200'
                : 'text-red-800 dark:text-red-200'
            }`}>
              {validationResult.is_valid ? t('validationPassed') : t('validationFailed')}
            </h4>

            {validationResult.pack_id && (
              <p className="text-sm text-slate-700 dark:text-slate-300">
                {t('packId')}: {validationResult.pack_id}
              </p>
            )}
            {validationResult.pack_name && (
              <p className="text-sm text-slate-700 dark:text-slate-300">
                {t('packName')}: {validationResult.pack_name}
              </p>
            )}

            {renderIssues(validationResult.issues)}
          </div>
        )}

        {importResult && renderImportResult(importResult)}
      </div>

      {showImportConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-slate-800 rounded-lg p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
              {t('confirmImport')}
            </h3>
            <p className="text-slate-700 dark:text-slate-300 mb-4">
              {t('confirmImportMessage', { path })}
            </p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setShowImportConfirm(false)}>
                {t('cancel')}
              </Button>
              <Button variant="danger" onClick={handleImport}>
                {t('import')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
