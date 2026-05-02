'use client';

import React from 'react';

interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'outlined' | 'elevated';
  padding?: 'none' | 'sm' | 'md' | 'lg';
}

export function Card({
  children,
  variant = 'default',
  padding = 'md',
  className = '',
  ...props
}: CardProps) {
  const variants = {
    default: 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700',
    outlined: 'bg-transparent border-2 border-slate-200 dark:border-slate-700',
    elevated: 'bg-white dark:bg-slate-800 shadow-lg shadow-slate-200/50 dark:shadow-black/50',
  };

  const paddings = {
    none: '',
    sm: 'p-3',
    md: 'p-5',
    lg: 'p-8',
  };

  return (
    <div
      className={`rounded-xl ${variants[variant]} ${paddings[padding]} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

interface CardHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
}

export function CardHeader({ title, subtitle, action, className = '', children, ...props }: CardHeaderProps) {
  return (
    <div className={`flex items-start justify-between mb-4 ${className}`} {...props}>
      <div className="flex-1">
        {title && (
          <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
        )}
        {subtitle && (
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{subtitle}</p>
        )}
        {children}
      </div>
      {action && <div className="ml-4">{action}</div>}
    </div>
  );
}

export function CardContent({ children, className = '', ...props }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`text-slate-700 dark:text-slate-300 ${className}`} {...props}>
      {children}
    </div>
  );
}

interface CardFooterProps {
  children: React.ReactNode;
  align?: 'left' | 'center' | 'right';
  className?: string;
}

export function CardFooter({ children, align = 'right', className = '', ...props }: CardFooterProps) {
  const alignments = {
    left: 'justify-start',
    center: 'justify-center',
    right: 'justify-end',
  };

  return (
    <div className={`flex items-center gap-3 mt-4 pt-4 border-t border-slate-200 dark:border-slate-700 ${alignments[align]} ${className}`} {...props}>
      {children}
    </div>
  );
}
