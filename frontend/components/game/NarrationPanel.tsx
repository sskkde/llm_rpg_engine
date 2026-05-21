'use client';

import {useTranslations} from 'next-intl';
import { Badge } from '@/components/ui/Badge';

interface NarrationPanelProps {
  narration: string;
  isStreaming: boolean;
  isComplete?: boolean;
  streamingDuration?: number;
  streamingProgress?: number;
}

function TypingIndicator() {
  return (
    <div className="flex items-center gap-1.5 py-2">
      <span className="w-1.5 h-1.5 bg-indigo-500 dark:bg-indigo-400 rounded-full animate-typing-dot-1" />
      <span className="w-1.5 h-1.5 bg-indigo-500 dark:bg-indigo-400 rounded-full animate-typing-dot-2" />
      <span className="w-1.5 h-1.5 bg-indigo-500 dark:bg-indigo-400 rounded-full animate-typing-dot-3" />
    </div>
  );
}

function StreamingCursor() {
  return (
    <span className="inline-block w-0.5 h-5 bg-indigo-500 dark:bg-indigo-400 ml-0.5 animate-streaming-cursor" />
  );
}

function StreamingBadge({ duration }: { duration: number }) {
  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return (
    <div className="absolute top-3 right-3 flex items-center gap-2">
      <Badge variant="info" size="sm" className="animate-streaming-indicator">
        <span className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 bg-sky-500 dark:bg-sky-400 rounded-full" />
          {formatDuration(duration)}
        </span>
      </Badge>
    </div>
  );
}

function CharacterCount({ count }: { count: number }) {
  return (
    <span className="text-xs text-slate-400 dark:text-slate-500 tabular-nums">
      {count.toLocaleString()} 字符
    </span>
  );
}

export function NarrationPanel({ 
  narration, 
  isStreaming, 
  isComplete = false,
  streamingDuration = 0,
  streamingProgress,
}: NarrationPanelProps) {
  const t = useTranslations('Game');
  const charCount = narration.length;
  const showTypingIndicator = isStreaming && !narration;
  const showStreamingContent = isStreaming && narration;
  const showCompletedContent = !isStreaming && narration;
  const showPlaceholder = !isStreaming && !narration;

  return (
    <div 
      data-testid="narration-panel" 
      className="relative bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 p-6 min-h-[200px]"
    >
      {isStreaming && <StreamingBadge duration={streamingDuration} />}
      
      <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 mb-3">
        {t('narration')}
      </h3>

      {showTypingIndicator && (
        <div className="flex flex-col items-center justify-center py-8 gap-3">
          <TypingIndicator />
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {t('storyUnfolds')}
          </span>
        </div>
      )}

      {showStreamingContent && (
        <div className="prose dark:prose-invert max-w-none">
          <p className="text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
            {narration}
            <StreamingCursor />
          </p>
          <div className="flex items-center justify-between mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
            <CharacterCount count={charCount} />
            {streamingProgress !== undefined && (
              <span className="text-xs text-slate-400 dark:text-slate-500">
                {streamingProgress}%
              </span>
            )}
          </div>
        </div>
      )}

      {showCompletedContent && (
        <div className={`prose dark:prose-invert max-w-none ${isComplete ? 'animate-fade-in-narration' : ''}`}>
          <p className="text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-wrap">
            {narration}
          </p>
        </div>
      )}

      {showPlaceholder && (
        <p className="text-slate-400 dark:text-slate-500 italic">
          {t('enterActionToBegin')}
        </p>
      )}
    </div>
  );
}
