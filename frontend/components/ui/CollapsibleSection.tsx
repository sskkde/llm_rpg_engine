'use client';

import React, { useState, useId } from 'react';

interface CollapsibleSectionProps {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onToggle?: (isOpen: boolean) => void;
  summary?: React.ReactNode;
  id?: string;
}

export function CollapsibleSection({
  title,
  children,
  defaultOpen = false,
  open: controlledOpen,
  onToggle,
  summary,
  id: providedId,
}: CollapsibleSectionProps) {
  const generatedId = useId();
  const sectionId = providedId || `collapsible-${generatedId}`;
  const contentId = `${sectionId}-content`;

  const isControlled = controlledOpen !== undefined;
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;

  const handleToggle = () => {
    const newState = !isOpen;
    if (!isControlled) {
      setUncontrolledOpen(newState);
    }
    onToggle?.(newState);
  };

  return (
    <div
      className="bg-white dark:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden"
    >
      <button
        type="button"
        id={sectionId}
        aria-expanded={isOpen}
        aria-controls={contentId}
        onClick={handleToggle}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 min-h-[44px] text-left hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-indigo-500 dark:focus:ring-indigo-400"
      >
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <span className="font-medium text-slate-900 dark:text-slate-100">
            {title}
          </span>
          {summary && (
            <span className="text-sm text-slate-500 dark:text-slate-400 truncate">
              {summary}
            </span>
          )}
        </div>
        <span className="flex-shrink-0 text-slate-400 dark:text-slate-500" aria-hidden="true">
          {isOpen ? (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          )}
        </span>
      </button>
      <div
        id={contentId}
        aria-labelledby={sectionId}
        hidden={!isOpen}
        className={`${isOpen ? 'block' : 'hidden'}`}
      >
        {children}
      </div>
    </div>
  );
}
