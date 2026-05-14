import {screen} from '@testing-library/react';
import {renderWithIntl} from '@/test-utils';
import {DebugEmptyState} from '@/components/debug/DebugEmptyState';

describe('DebugEmptyState', () => {
  it('renders with default message', () => {
    renderWithIntl(<DebugEmptyState />);

    expect(screen.getByText('无数据')).toBeInTheDocument();
  });

  it('renders with custom message', () => {
    renderWithIntl(<DebugEmptyState message="No session loaded" />);

    expect(screen.getByText('No session loaded')).toBeInTheDocument();
  });

  it('renders icon', () => {
    const {container} = renderWithIntl(<DebugEmptyState />);

    const svg = container.querySelector('svg');
    expect(svg).toBeInTheDocument();
  });

  it('applies custom className', () => {
    const {container} = renderWithIntl(<DebugEmptyState className="custom-class" />);

    expect(container.firstChild).toHaveClass('custom-class');
  });
});
