import {act, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {AuthProvider, useAuth} from '@/hooks/useAuth';
import {getCurrentUser, loginUser} from '@/lib/api';
import type {User} from '@/types/api';

jest.mock('@/lib/api', () => ({
  getCurrentUser: jest.fn(),
  loginUser: jest.fn(),
  registerUser: jest.fn(),
}));

const mockGetCurrentUser = jest.mocked(getCurrentUser);
const mockLoginUser = jest.mocked(loginUser);

const user: User = {
  id: 'user-1',
  username: 'testuser',
  created_at: '2026-05-04T00:00:00Z',
};

function AuthProbe() {
  const {isAuthenticated, isLoading, login, user: currentUser} = useAuth();

  return (
    <div>
      <span data-testid="auth-state">{isAuthenticated ? 'authenticated' : 'anonymous'}</span>
      <span data-testid="loading-state">{isLoading ? 'loading' : 'ready'}</span>
      <span data-testid="username">{currentUser?.username ?? 'none'}</span>
      <button type="button" onClick={() => void login('testuser', 'password123')}>
        login
      </button>
    </div>
  );
}

describe('AuthProvider login flow', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  it('keeps a successful login when stale startup auth validation fails later', async () => {
    let rejectStartupValidation!: (error: Error) => void;
    const startupValidation = new Promise<User>((_, reject) => {
      rejectStartupValidation = reject;
    });

    localStorage.setItem('access_token', 'stale-token');
    mockGetCurrentUser.mockReturnValue(startupValidation);
    mockLoginUser.mockResolvedValue({
      access_token: 'fresh-token',
      token_type: 'bearer',
      user,
    });

    render(
      <AuthProvider>
        <AuthProbe />
      </AuthProvider>
    );

    fireEvent.click(screen.getByRole('button', {name: 'login'}));

    await waitFor(() => {
      expect(screen.getByTestId('auth-state')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('loading-state')).toHaveTextContent('ready');
      expect(screen.getByTestId('username')).toHaveTextContent('testuser');
      expect(localStorage.getItem('access_token')).toBe('fresh-token');
    });

    await act(async () => {
      rejectStartupValidation(new Error('stale token'));
      await startupValidation.catch(() => undefined);
    });

    expect(screen.getByTestId('auth-state')).toHaveTextContent('authenticated');
    expect(screen.getByTestId('loading-state')).toHaveTextContent('ready');
    expect(localStorage.getItem('access_token')).toBe('fresh-token');
  });
});
