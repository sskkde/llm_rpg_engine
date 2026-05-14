'use client';

import React, { useCallback } from 'react';
import { useTranslations } from 'next-intl';
import { Card, CardHeader, CardContent, CardFooter } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import { StateDiffViewer } from '@/components/debug/StateDiffViewer';
import type { ReplayReportResponse } from '@/types/api';

interface ReplayReportViewerProps {
  report: ReplayReportResponse;
  onClose?: () => void;
}

export function ReplayReportViewer({ report, onClose }: ReplayReportViewerProps) {
  const t = useTranslations('Debug');

  const handleDownload = useCallback(() => {
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `replay-report-${report.session_id}-${report.from_turn}-${report.to_turn}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }, [report]);

  return (
    <Card className="p-6">
      <CardHeader
        title={t('replayReport')}
        subtitle={`${t('turnRange')}: ${report.from_turn} - ${report.to_turn}`}
        action={
          <Button variant="outline" size="sm" onClick={handleDownload}>
            {t('downloadJson')}
          </Button>
        }
      />

      <CardContent className="space-y-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div className="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
            <span className="text-slate-500 dark:text-slate-400 block text-xs mb-1">
              {t('deterministic')}
            </span>
            <span
              className={
                report.deterministic
                  ? 'text-green-600 dark:text-green-400 font-medium'
                  : 'text-amber-600 dark:text-amber-400 font-medium'
              }
            >
              {report.deterministic ? t('pass') : t('warning')}
            </span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
            <span className="text-slate-500 dark:text-slate-400 block text-xs mb-1">
              {t('llmCalls')}
            </span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {report.llm_calls_made}
            </span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
            <span className="text-slate-500 dark:text-slate-400 block text-xs mb-1">
              {t('events')}
            </span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {report.replayed_event_count}
            </span>
          </div>

          <div className="bg-slate-50 dark:bg-slate-800/50 p-3 rounded-lg">
            <span className="text-slate-500 dark:text-slate-400 block text-xs mb-1">
              {t('stateChanges')}
            </span>
            <span className="font-medium text-slate-900 dark:text-slate-100">
              {report.state_diff.entries.length}
            </span>
          </div>
        </div>

        {report.warnings.length > 0 && (
          <CollapsibleSection
            title={t('warnings')}
            summary={`(${report.warnings.length})`}
            defaultOpen={report.warnings.length <= 5}
          >
            <div className="p-4 space-y-2">
              {report.warnings.map((warning, index) => (
                <div
                  key={index}
                  className="text-sm p-2 bg-amber-50 dark:bg-amber-900/20 rounded text-amber-700 dark:text-amber-300"
                >
                  {warning}
                </div>
              ))}
            </div>
          </CollapsibleSection>
        )}

        <CollapsibleSection
          title={t('stateDiff')}
          summary={`(${report.state_diff.entries.length})`}
          defaultOpen={report.state_diff.entries.length > 0}
        >
          <div className="p-4">
            <StateDiffViewer stateDiff={report.state_diff} />
          </div>
        </CollapsibleSection>
      </CardContent>

      {onClose && (
        <CardFooter align="right">
          <Button variant="ghost" onClick={onClose}>
            {t('close')}
          </Button>
        </CardFooter>
      )}
    </Card>
  );
}
