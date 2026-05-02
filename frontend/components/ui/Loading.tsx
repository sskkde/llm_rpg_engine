'use client';

import React from 'react';

interface LoadingProps {
  size?: 'sm' | 'md' | 'lg' | 'xl';
  variant?: 'spinner' | 'dots' | 'pulse';
  text?: string;
  fullScreen?: boolean;
  className?: string;
}

export function Loading({
  size = 'md',
  variant = 'spinner',
  text,
  fullScreen = false,
  className = '',
}: LoadingProps) {
  const sizes = {
    sm: 'w-4 h-4',
    md: 'w-8 h-8',
    lg: 'w-12 h-12',
    xl: 'w-16 h-16',
  };

  const textSizes = {
    sm: 'text-xs',
    md: 'text-sm',
    lg: 'text-base',
    xl: 'text-lg',
  };

  const renderSpinner = () => (
    <div className={`${sizes[size]} ${className}`}>
      <svg
        className="animate-spin w-full h-full text-indigo-600 dark:text-indigo-400"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle
          className="opacity-25"
          cx="12"
          cy="12"
          r="10"
          stroke="currentColor"
          strokeWidth="4"
        />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
        />
      </svg>
    </div>
  );

  const renderDots = () => (
    <div className={`flex items-center gap-1 ${className}`}>
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={`
            ${sizes[size] === 'w-4 h-4' ? 'w-1.5 h-1.5' : ''}
            ${sizes[size] === 'w-8 h-8' ? 'w-2 h-2' : ''}
            ${sizes[size] === 'w-12 h-12' ? 'w-3 h-3' : ''}
            ${sizes[size] === 'w-16 h-16' ? 'w-4 h-4' : ''}
            bg-indigo-600 dark:bg-indigo-400 rounded-full animate-bounce
          `}
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  );

  const renderPulse = () => (
    <div className={`${sizes[size]} relative ${className}`}>
      <div className="absolute inset-0 bg-indigo-600 dark:bg-indigo-400 rounded-full animate-ping opacity-75" />
      <div className="relative w-full h-full bg-indigo-600 dark:bg-indigo-400 rounded-full" />
    </div>
  );

  const content = (
    <div className="flex flex-col items-center gap-3">
      {variant === 'spinner' && renderSpinner()}
      {variant === 'dots' && renderDots()}
      {variant === 'pulse' && renderPulse()}
      {text && (
        <span className={`${textSizes[size]} text-slate-600 dark:text-slate-400 font-medium`}>
          {text}
        </span>
      )}
    </div>
  );

  if (fullScreen) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm">
        {content}
      </div>
    );
  }

  return content;
}

interface LoadingOverlayProps {
  isLoading: boolean;
  children: React.ReactNode;
  text?: string;
}

export function LoadingOverlay({ isLoading, children, text }: LoadingOverlayProps) {
  return (
    <div className="relative">
      {children}
      {isLoading && (
        <div className="absolute inset-0 flex items-center justify-center bg-white/70 dark:bg-slate-900/70 backdrop-blur-sm rounded-lg z-10">
          <Loading size="md" text={text} />
        </div>
      )}
    </div>
  );
}
