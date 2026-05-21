/**
 * TEST DEBT STATUS: Fixed (was skipped with P4 TODO)
 * Original issue: React 19 / testing-library compatibility - tests rendered empty <div />
 * Resolution: The compatibility issue has been resolved; tests now pass with renderWithIntl.
 * Remaining debt: None for this file.
 */
import { screen, fireEvent } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { ActionInput } from '@/components/game/ActionInput';

describe('ActionInput', () => {
  const onSubmit = jest.fn();
  let consoleError: jest.SpyInstance;

  beforeEach(() => {
    jest.clearAllMocks();
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    consoleError.mockRestore();
  });

  it('renders input and submit button', () => {
    renderWithIntl(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    if (consoleError.mock.calls.length > 0) {
      console.log('Console errors:', consoleError.mock.calls);
    }
    expect(screen.getByTestId('action-input')).toBeInTheDocument();
    expect(screen.getByTestId('action-submit')).toBeInTheDocument();
  });

  it('calls onSubmit with action text', () => {
    renderWithIntl(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    fireEvent.change(screen.getByTestId('action-input'), { target: { value: '观察四周' } });
    fireEvent.submit(screen.getByTestId('action-input').closest('form')!);
    expect(onSubmit).toHaveBeenCalledWith('观察四周');
  });

  it('does not submit empty action', () => {
    renderWithIntl(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    fireEvent.submit(screen.getByTestId('action-input').closest('form')!);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables input when isDisabled', () => {
    renderWithIntl(<ActionInput onSubmit={onSubmit} isDisabled={true} />);
    expect(screen.getByTestId('action-input')).toBeDisabled();
  });
});
