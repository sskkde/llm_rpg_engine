import type {Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

export interface A11yCheckOptions {
  includeRules?: string[];
  excludeRules?: string[];
  scope?: string;
  includeBestPractices?: boolean;
}

export async function checkA11y(page: Page, options: A11yCheckOptions = {}) {
  let builder = new AxeBuilder({page});

  if (options.scope) {
    builder = builder.include(options.scope);
  }

  if (options.includeBestPractices) {
    builder = builder.withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']);
  } else {
    builder = builder.withTags(['wcag2a', 'wcag2aa', 'wcag21aa']);
  }

  if (options.includeRules?.length) {
    builder = builder.withRules(options.includeRules);
  }

  if (options.excludeRules?.length) {
    builder = builder.disableRules(options.excludeRules);
  }

  return await builder.analyze();
}

export async function assertNoA11yViolations(
  page: Page,
  options: A11yCheckOptions = {}
): Promise<void> {
  const results = await checkA11y(page, options);

  if (results.violations.length > 0) {
    const violationsSummary = results.violations
      .map(
        v =>
          `  - ${v.id}: ${v.description} (${v.impact}) - Affected nodes: ${v.nodes.length}`
      )
      .join('\n');

    throw new Error(
      `Accessibility violations found (${results.violations.length}):\n${violationsSummary}`
    );
  }
}

export function formatViolations(
  violations: Awaited<ReturnType<AxeBuilder['analyze']>>['violations']
): string {
  if (violations.length === 0) {
    return 'No accessibility violations found.';
  }

  return violations
    .map(v => {
      const nodes = v.nodes
        .map(
          n =>
            `    - ${n.target.join(', ')}: ${n.failureSummary || 'No additional details'}`
        )
        .join('\n');

      return `  ${v.id} (${v.impact}): ${v.description}\n${nodes}`;
    })
    .join('\n\n');
}
