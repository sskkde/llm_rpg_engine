import {screen, fireEvent} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {DebugErrorBoundary} from '@/components/debug/DebugErrorBoundary';

// Component that throws an error for testing
function ThrowError({shouldThrow}: {shouldThrow: boolean}) {
  if (shouldThrow) {
    throw new Error('Test error');
  }
  return <div>Normal content</div>;
}

describe('DebugErrorBoundary', () => {
  // Suppress console.error during tests
  const originalError = console.error;
  beforeAll(() => {
    console.error = jest.fn();
  });
  afterAll(() => {
    console.error = originalError;
  });

  it('renders children when no error', () => {
    renderWithIntl(
      <DebugErrorBoundary>
        <div>Test content</div>
      </DebugErrorBoundary>
    );

    expect(screen.getByText('Test content')).toBeInTheDocument();
  });

  it('renders error UI when child throws', () => {
    renderWithIntl(
      <DebugErrorBoundary>
        <ThrowError shouldThrow />
      </DebugErrorBoundary>
    );

    expect(screen.getByText(/调试视图发生错误/)).toBeInTheDocument();
  });

  it('calls onRetry when retry button clicked', () => {
    const mockOnRetry = jest.fn();
    renderWithIntl(
      <DebugErrorBoundary onRetry={mockOnRetry}>
        <ThrowError shouldThrow />
      </DebugErrorBoundary>
    );

    const retryButton = screen.getByRole('button', {name: /重试/});
    fireEvent.click(retryButton);

    expect(mockOnRetry).toHaveBeenCalled();
  });

  it('displays custom message when provided', () => {
    renderWithIntl(
      <DebugErrorBoundary message="Custom error message">
        <ThrowError shouldThrow />
      </DebugErrorBoundary>
    );

    expect(screen.getByText('Custom error message')).toBeInTheDocument();
  });
});
