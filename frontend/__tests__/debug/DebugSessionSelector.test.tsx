import {screen, fireEvent} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {DebugSessionSelector} from '@/components/debug/DebugSessionSelector';

describe('DebugSessionSelector', () => {
  const mockOnLoad = jest.fn();

  beforeEach(() => {
    mockOnLoad.mockClear();
  });

  it('renders input and load button', () => {
    renderWithIntl(<DebugSessionSelector onLoad={mockOnLoad} />);

    expect(screen.getByPlaceholderText('输入会话ID')).toBeInTheDocument();
    expect(screen.getByRole('button', {name: '加载'})).toBeInTheDocument();
  });

  it('disables load button when input is empty', () => {
    renderWithIntl(<DebugSessionSelector onLoad={mockOnLoad} />);

    const loadButton = screen.getByRole('button', {name: '加载'});
    expect(loadButton).toBeDisabled();
  });

  it('enables load button when input has value', () => {
    renderWithIntl(<DebugSessionSelector onLoad={mockOnLoad} />);

    const input = screen.getByPlaceholderText('输入会话ID');
    fireEvent.change(input, {target: {value: 'test-session-123'}});

    const loadButton = screen.getByRole('button', {name: '加载'});
    expect(loadButton).not.toBeDisabled();
  });

  it('calls onLoad with session ID when button clicked', () => {
    renderWithIntl(<DebugSessionSelector onLoad={mockOnLoad} />);

    const input = screen.getByPlaceholderText('输入会话ID');
    fireEvent.change(input, {target: {value: 'test-session-123'}});

    const loadButton = screen.getByRole('button', {name: '加载'});
    fireEvent.click(loadButton);

    expect(mockOnLoad).toHaveBeenCalledWith('test-session-123');
  });

  it('disables button when loading', () => {
    renderWithIntl(<DebugSessionSelector onLoad={mockOnLoad} isLoading />);

    const loadButton = screen.getByRole('button', {name: '加载'});
    expect(loadButton).toBeDisabled();
  });

  it('shows current session ID when provided', () => {
    renderWithIntl(
      <DebugSessionSelector onLoad={mockOnLoad} currentSessionId="existing-session" />
    );

    const input = screen.getByDisplayValue('existing-session');
    expect(input).toBeInTheDocument();
  });
});
