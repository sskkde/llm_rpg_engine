import {screen, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';

jest.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ isAuthenticated: true, isLoading: false, user: { username: 'admin' } }),
}));

jest.mock('@/lib/api', () => ({
  listWorlds: jest.fn().mockResolvedValue([]),
  updateWorld: jest.fn(),
}));

describe('Admin Dashboard', () => {
  it('renders admin page', async () => {
    const AdminPage = (await import('@/app/[locale]/admin/page')).default;
    renderWithIntl(<AdminPage />, {locale: 'en'});
    expect(screen.getByText('Admin Dashboard')).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByText('No items found')).toBeInTheDocument();
    });
  });
});
