import { screen } from '@testing-library/react';
import { renderWithIntl } from '@/test-utils';
import { SceneBackground } from '@/components/assets/SceneBackground';

describe('SceneBackground', () => {
  it('renders with placeholder text', () => {
    renderWithIntl(<SceneBackground locationId="loc-1" />);
    expect(screen.getByText('场景背景')).toBeInTheDocument();
  });

  it('renders night gradient', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" timeOfDay="night" />);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('indigo-900');
  });

  it('renders rainy gradient', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" weather="rainy" />);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('slate-400');
  });

  it('renders snowy gradient', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" weather="snowy" />);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('blue-100');
  });

  it('renders default day gradient', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" />);
    const div = container.firstChild as HTMLElement;
    expect(div.className).toContain('blue-300');
  });

  it('includes locationId data attribute', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-123" />);
    const div = container.firstChild as HTMLElement;
    expect(div.dataset.locationId).toBe('loc-123');
  });

  it('includes sessionId data attribute when provided', () => {
    const { container } = renderWithIntl(<SceneBackground locationId="loc-1" sessionId="session-456" />);
    const div = container.firstChild as HTMLElement;
    expect(div.dataset.sessionId).toBe('session-456');
  });
});
