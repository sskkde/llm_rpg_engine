import { render, screen, fireEvent } from '@testing-library/react';
import { ActionInput } from '@/components/game/ActionInput';

describe('ActionInput', () => {
  const onSubmit = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders input and submit button', () => {
    render(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    expect(screen.getByTestId('action-input')).toBeInTheDocument();
    expect(screen.getByTestId('action-submit')).toBeInTheDocument();
  });

  it('calls onSubmit with action text', () => {
    render(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    fireEvent.change(screen.getByTestId('action-input'), { target: { value: '观察四周' } });
    fireEvent.submit(screen.getByTestId('action-input').closest('form')!);
    expect(onSubmit).toHaveBeenCalledWith('观察四周');
  });

  it('does not submit empty action', () => {
    render(<ActionInput onSubmit={onSubmit} isDisabled={false} />);
    fireEvent.submit(screen.getByTestId('action-input').closest('form')!);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('disables input when isDisabled', () => {
    render(<ActionInput onSubmit={onSubmit} isDisabled={true} />);
    expect(screen.getByTestId('action-input')).toBeDisabled();
  });
});
