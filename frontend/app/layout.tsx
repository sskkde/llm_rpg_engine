import './globals.css';

export const metadata = {
  title: 'RPG Engine',
  description: 'LLM-powered narrative RPG engine',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh" className="h-full antialiased" suppressHydrationWarning>
      <body className="min-h-full flex flex-col bg-slate-50 dark:bg-slate-900">
        {children}
      </body>
    </html>
  );
}
