'use client';

import React, { createContext, useContext, useRef, useState } from 'react';

interface TabsContextType {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  tabRefs: React.RefObject<Map<string, HTMLButtonElement>>;
}

const TabsContext = createContext<TabsContextType | undefined>(undefined);

function useTabs() {
  const context = useContext(TabsContext);
  if (context === undefined) {
    throw new Error('Tab components must be used within a Tabs provider');
  }
  return context;
}

interface TabsProps {
  children: React.ReactNode;
  defaultTab: string;
  className?: string;
}

export function Tabs({ children, defaultTab, className = '' }: TabsProps) {
  const [activeTab, setActiveTab] = useState(defaultTab);
  const tabRefs = useRef<Map<string, HTMLButtonElement>>(new Map());

  return (
    <TabsContext.Provider value={{ activeTab, setActiveTab, tabRefs }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

interface TabListProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode;
}

export function TabList({ children, className = '', ...props }: TabListProps) {
  const { setActiveTab, tabRefs } = useTabs();

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const tabElements = Array.from(tabRefs.current.values()).filter(Boolean);
    if (tabElements.length === 0) return;

    const currentIndex = tabElements.findIndex(tab => tab.getAttribute('aria-selected') === 'true');
    let nextIndex = currentIndex;

    switch (event.key) {
      case 'ArrowLeft':
        event.preventDefault();
        nextIndex = currentIndex <= 0 ? tabElements.length - 1 : currentIndex - 1;
        break;
      case 'ArrowRight':
        event.preventDefault();
        nextIndex = currentIndex >= tabElements.length - 1 ? 0 : currentIndex + 1;
        break;
      case 'Home':
        event.preventDefault();
        nextIndex = 0;
        break;
      case 'End':
        event.preventDefault();
        nextIndex = tabElements.length - 1;
        break;
      default:
        return;
    }

    if (nextIndex !== currentIndex && nextIndex >= 0) {
      const nextTab = tabElements[nextIndex];
      if (nextTab) {
        const tabValue = nextTab.getAttribute('data-tab-value');
        if (tabValue) {
          setActiveTab(tabValue);
          nextTab.focus();
        }
      }
    }
  };

  return (
    <div
      role="tablist"
      className={`flex border-b border-slate-200 dark:border-slate-700 overflow-x-auto whitespace-nowrap ${className}`}
      onKeyDown={handleKeyDown}
      {...props}
    >
      {children}
    </div>
  );
}

interface TabProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  value: string;
  children: React.ReactNode;
}

export function Tab({ value, children, className = '', ...props }: TabProps) {
  const { activeTab, setActiveTab, tabRefs } = useTabs();
  const isActive = activeTab === value;
  const tabId = `tab-${value}`;
  const panelId = `tabpanel-${value}`;

  const refCallback = (node: HTMLButtonElement | null) => {
    if (node) {
      tabRefs.current.set(value, node);
    }
  };

  return (
    <button
      ref={refCallback}
      type="button"
      role="tab"
      id={tabId}
      aria-selected={isActive}
      aria-controls={panelId}
      tabIndex={isActive ? 0 : -1}
      data-tab-value={value}
      onClick={() => setActiveTab(value)}
      className={`
        flex-none px-4 py-2 text-sm font-medium border-b-2 transition-colors duration-200
        ${isActive
          ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
          : 'border-transparent text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300'
        }
        ${className}
      `}
      {...props}
    >
      {children}
    </button>
  );
}

interface TabPanelProps extends React.HTMLAttributes<HTMLDivElement> {
  value: string;
  children: React.ReactNode;
}

export function TabPanel({ value, children, className = '', ...props }: TabPanelProps) {
  const { activeTab } = useTabs();

  if (activeTab !== value) {
    return null;
  }

  const panelId = `tabpanel-${value}`;
  const tabId = `tab-${value}`;

  return (
    <div
      id={panelId}
      role="tabpanel"
      aria-labelledby={tabId}
      className={`py-4 ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
