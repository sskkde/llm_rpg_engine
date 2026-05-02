import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {LoginForm} from '@/components/auth/LoginForm';

const mockPush = jest.fn();
const mockLogin = jest.fn();

jest.mock('@/i18n/navigation', () => ({
  useRouter: () => ({push: mockPush}),
}));

jest.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({login: mockLogin}),
}));

jest.mock('@/lib/api', () => ({
  APIError: class APIError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = 'APIError';
    }
  },
}));

describe('LoginForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders username and password fields', () => {
    renderWithIntl(<LoginForm />);
    expect(screen.getByTestId('username-input')).toBeInTheDocument();
    expect(screen.getByTestId('password-input')).toBeInTheDocument();
    expect(screen.getByTestId('login-submit')).toBeInTheDocument();
  });

  it('calls login on submit', async () => {
    mockLogin.mockResolvedValue(undefined);
    renderWithIntl(<LoginForm />);

    fireEvent.change(screen.getByTestId('username-input'), {target: {value: 'testuser'}});
    fireEvent.change(screen.getByTestId('password-input'), {target: {value: 'password123'}});
    fireEvent.submit(screen.getByTestId('login-submit').closest('form')!);

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith('testuser', 'password123');
      expect(mockPush).toHaveBeenCalledWith('/saves');
    });
  });

  it('shows error on empty fields', async () => {
    renderWithIntl(<LoginForm />);
    fireEvent.submit(screen.getByTestId('login-submit').closest('form')!);

    await waitFor(() => {
      expect(screen.getByTestId('login-error')).toBeInTheDocument();
    });
    expect(mockLogin).not.toHaveBeenCalled();
  });

  it('shows error on API failure', async () => {
    const {APIError} = await import('@/lib/api');
    mockLogin.mockRejectedValue(new APIError(401, 'Invalid credentials'));
    renderWithIntl(<LoginForm />);

    fireEvent.change(screen.getByTestId('username-input'), {target: {value: 'baduser'}});
    fireEvent.change(screen.getByTestId('password-input'), {target: {value: 'badpass'}});
    fireEvent.submit(screen.getByTestId('login-submit').closest('form')!);

    await waitFor(() => {
      expect(screen.getByTestId('login-error')).toBeInTheDocument();
    });
  });

  it('renders Chinese labels when locale is zh', () => {
    renderWithIntl(<LoginForm />, {locale: 'zh'});
    expect(screen.getByText('登录')).toBeInTheDocument();
  });

  it('renders English labels when locale is en', () => {
    renderWithIntl(<LoginForm />, {locale: 'en'});
    expect(screen.getByText('Login')).toBeInTheDocument();
  });
});
