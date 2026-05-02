import {useTranslations} from 'next-intl';
import { Loading } from '@/components/ui/Loading';

export default function RootLoading() {
  const t = useTranslations('Common');

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-900">
      <Loading size="xl" variant="spinner" text={t('loadingAdventure')} />
    </div>
  );
}
