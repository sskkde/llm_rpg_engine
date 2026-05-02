import {screen, fireEvent, waitFor} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import { RegisterForm } from '@/components/auth/RegisterForm';

const mockPush = jest.fn();
const mockRegister = jest.fn();

jest.mock('@/i18n/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

jest.mock('@/hooks/useAuth', () => ({
  useAuth: () => ({ register: mockRegister }),
}));

jest.mock('@/lib/api', () => ({
  APIError: class APIError extends Error {
    constructor(public status: number, public detail: string) {
      super(detail);
      this.name = 'APIError';
    }
  },
}));

describe('RegisterForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders all fields', () => {
    renderWithIntl(<RegisterForm />, {locale: 'en'});
    expect(screen.getByTestId('register-username-input')).toBeInTheDocument();
    expect(screen.getByTestId('register-email-input')).toBeInTheDocument();
    expect(screen.getByTestId('register-password-input')).toBeInTheDocument();
    expect(screen.getByTestId('register-submit')).toBeInTheDocument();
  });

  it('calls register on submit', async () => {
    mockRegister.mockResolvedValue(undefined);
    renderWithIntl(<RegisterForm />, {locale: 'en'});

    fireEvent.change(screen.getByTestId('register-username-input'), { target: { value: 'newuser' } });
    fireEvent.change(screen.getByTestId('register-email-input'), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByTestId('register-password-input'), { target: { value: 'password123' } });
    fireEvent.submit(screen.getByTestId('register-submit').closest('form')!);

    await waitFor(() => {
      expect(mockRegister).toHaveBeenCalledWith('newuser', 'password123', 'test@example.com');
      expect(mockPush).toHaveBeenCalledWith('/auth/login?registered=1');
    });
  });

  it('shows error on empty required fields', async () => {
    renderWithIntl(<RegisterForm />, {locale: 'en'});
    fireEvent.submit(screen.getByTestId('register-submit').closest('form')!);

    await waitFor(() => {
      expect(screen.getByText(/username and password are required/i)).toBeInTheDocument();
    });
    expect(mockRegister).not.toHaveBeenCalled();
  });

  it('shows error on duplicate username (409)', async () => {
    const { APIError } = await import('@/lib/api');
    mockRegister.mockRejectedValue(new APIError(409, 'Username already exists'));
    renderWithIntl(<RegisterForm />, {locale: 'en'});

    fireEvent.change(screen.getByTestId('register-username-input'), { target: { value: 'existing' } });
    fireEvent.change(screen.getByTestId('register-password-input'), { target: { value: 'password123' } });
    fireEvent.submit(screen.getByTestId('register-submit').closest('form')!);

    await waitFor(() => {
      expect(screen.getByText(/username already exists/i)).toBeInTheDocument();
    });
  });
});
