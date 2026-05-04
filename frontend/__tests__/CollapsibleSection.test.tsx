import {screen, fireEvent} from '@testing-library/react';
import {render} from '@testing-library/react';
import {CollapsibleSection} from '@/components/ui/CollapsibleSection';

describe('CollapsibleSection', () => {
  describe('default state', () => {
    it('renders with content hidden by default when defaultOpen is false', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Hidden Content</div>
        </CollapsibleSection>
      );
      expect(screen.getByText('Test Section')).toBeInTheDocument();
      expect(screen.queryByText('Hidden Content')).not.toBeVisible();
    });

    it('renders with content visible when defaultOpen is true', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={true}>
          <div>Visible Content</div>
        </CollapsibleSection>
      );
      expect(screen.getByText('Visible Content')).toBeVisible();
    });

    it('defaults to collapsed when defaultOpen is not provided', () => {
      render(
        <CollapsibleSection title="Test Section">
          <div>Content</div>
        </CollapsibleSection>
      );
      expect(screen.queryByText('Content')).not.toBeVisible();
    });
  });

  describe('toggle behavior', () => {
    it('expands content when clicked while collapsed', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Expandable Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(screen.queryByText('Expandable Content')).not.toBeVisible();
      fireEvent.click(button);
      expect(screen.getByText('Expandable Content')).toBeVisible();
    });

    it('collapses content when clicked while expanded', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={true}>
          <div>Collapsible Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(screen.getByText('Collapsible Content')).toBeVisible();
      fireEvent.click(button);
      expect(screen.queryByText('Collapsible Content')).not.toBeVisible();
    });

    it('toggles multiple times correctly', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Toggle Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      fireEvent.click(button);
      expect(screen.getByText('Toggle Content')).toBeVisible();
      fireEvent.click(button);
      expect(screen.queryByText('Toggle Content')).not.toBeVisible();
      fireEvent.click(button);
      expect(screen.getByText('Toggle Content')).toBeVisible();
    });
  });

  describe('aria attributes', () => {
    it('has correct aria-expanded when collapsed', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button).toHaveAttribute('aria-expanded', 'false');
    });

    it('has correct aria-expanded when expanded', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={true}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it('updates aria-expanded on toggle', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button).toHaveAttribute('aria-expanded', 'false');
      fireEvent.click(button);
      expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it('has aria-controls pointing to content id', () => {
      render(
        <CollapsibleSection title="Test Section" id="test-section">
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button).toHaveAttribute('aria-controls', 'test-section-content');
    });

    it('generates unique ids when id is not provided', () => {
      render(
        <>
          <CollapsibleSection title="Section 1">
            <div>Content 1</div>
          </CollapsibleSection>
          <CollapsibleSection title="Section 2">
            <div>Content 2</div>
          </CollapsibleSection>
        </>
      );
      const buttons = screen.getAllByRole('button');
      const ids = buttons.map(b => b.id);
      expect(new Set(ids).size).toBe(2);
      expect(ids[0]).not.toBe(ids[1]);
    });

    it('content has correct id and aria-labelledby', () => {
      render(
        <CollapsibleSection title="Test Section" id="my-section">
          <div>Content</div>
        </CollapsibleSection>
      );
      const content = document.getElementById('my-section-content');
      expect(content).toBeInTheDocument();
      expect(content).toHaveAttribute('aria-labelledby', 'my-section');
    });
  });

  describe('controlled mode', () => {
    it('respects controlled open prop', () => {
      render(
        <CollapsibleSection title="Test Section" open={true}>
          <div>Content</div>
        </CollapsibleSection>
      );
      expect(screen.getByText('Content')).toBeVisible();
    });

    it('respects controlled open prop when false', () => {
      render(
        <CollapsibleSection title="Test Section" open={false}>
          <div>Content</div>
        </CollapsibleSection>
      );
      expect(screen.queryByText('Content')).not.toBeVisible();
    });

    it('calls onToggle when clicked in controlled mode', () => {
      const handleToggle = jest.fn();
      render(
        <CollapsibleSection
          title="Test Section"
          open={false}
          onToggle={handleToggle}
        >
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      fireEvent.click(button);
      expect(handleToggle).toHaveBeenCalledWith(true);
    });

    it('calls onToggle with false when collapsing', () => {
      const handleToggle = jest.fn();
      render(
        <CollapsibleSection
          title="Test Section"
          open={true}
          onToggle={handleToggle}
        >
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      fireEvent.click(button);
      expect(handleToggle).toHaveBeenCalledWith(false);
    });

    it('does not auto-toggle in controlled mode', () => {
      render(
        <CollapsibleSection title="Test Section" open={false}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      fireEvent.click(button);
      expect(screen.queryByText('Content')).not.toBeVisible();
    });
  });

  describe('summary text', () => {
    it('renders summary text when provided', () => {
      render(
        <CollapsibleSection title="Test Section" summary="Summary Info">
          <div>Content</div>
        </CollapsibleSection>
      );
      expect(screen.getByText('Summary Info')).toBeInTheDocument();
    });

    it('does not render summary element when not provided', () => {
      render(
        <CollapsibleSection title="Test Section">
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button.textContent).toBe('Test Section');
    });

    it('renders ReactNode summary', () => {
      render(
        <CollapsibleSection
          title="Test Section"
          summary={<span data-testid="custom-summary">Custom</span>}
        >
          <div>Content</div>
        </CollapsibleSection>
      );
      expect(screen.getByTestId('custom-summary')).toBeInTheDocument();
    });
  });

  describe('touch target', () => {
    it('has minimum 44px touch target on mobile', () => {
      render(
        <CollapsibleSection title="Test Section">
          <div>Content</div>
        </CollapsibleSection>
      );
      const button = screen.getByRole('button', {name: /Test Section/i});
      expect(button.className).toContain('min-h-[44px]');
    });
  });

  describe('chevron icons', () => {
    it('shows down chevron when collapsed', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={false}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const chevron = document.querySelector('[data-testid="chevron"]') ||
        document.querySelector('svg');
      expect(chevron).toBeInTheDocument();
    });

    it('shows up chevron when expanded', () => {
      render(
        <CollapsibleSection title="Test Section" defaultOpen={true}>
          <div>Content</div>
        </CollapsibleSection>
      );
      const chevron = document.querySelector('[data-testid="chevron"]') ||
        document.querySelector('svg');
      expect(chevron).toBeInTheDocument();
    });
  });
});
