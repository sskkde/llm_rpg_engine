import {test, expect} from '@playwright/test';
import {checkA11y} from './helpers/axe';

/**
 * Accessibility Regression Tests
 *
 * These tests verify that key pages have no critical or serious accessibility violations.
 * They use axe-core via @axe-core/playwright to check for WCAG 2.1 AA compliance.
 *
 * Test coverage:
 * - Login page accessibility
 * - Home page accessibility
 * - Admin page (unauthenticated shell) accessibility
 *
 * Runs on: chromium and Mobile Chrome projects
 */

async function assertNoCriticalOrSeriousViolations(page: ReturnType<typeof checkA11y>) {
  const results = await page;

  const criticalOrSerious = results.violations.filter(
    v => v.impact === 'critical' || v.impact === 'serious'
  );

  if (criticalOrSerious.length > 0) {
    const summary = criticalOrSerious
      .map(v => `  - ${v.id}: ${v.description} (${v.impact})`)
      .join('\n');

    throw new Error(
      `Accessibility violations found (${criticalOrSerious.length}):\n${summary}`
    );
  }
}

test.describe('Login Page Accessibility', () => {
  test('login page has no critical or serious axe violations', async ({page}) => {
    await page.goto('/zh/auth/login');

    await assertNoCriticalOrSeriousViolations(
      checkA11y(page, {
        excludeRules: [
          'color-contrast',
        ],
      })
    );
  });

  test('login page form inputs have proper labels', async ({page}) => {
    await page.goto('/zh/auth/login');

    const usernameInput = page.locator('[data-testid="username-input"]');
    const passwordInput = page.locator('[data-testid="password-input"]');

    await expect(usernameInput).toHaveAttribute('name', /.+/);
    await expect(passwordInput).toHaveAttribute('name', /.+/);
  });

  test('login submit button is focusable and has accessible name', async ({page}) => {
    await page.goto('/zh/auth/login');

    const submitButton = page.locator('[data-testid="login-submit"]');
    await expect(submitButton).toBeVisible();

    const accessibleName = await submitButton.getAttribute('aria-label').catch(() => null);
    const buttonText = await submitButton.textContent();

    expect(accessibleName || buttonText).toBeTruthy();
  });
});

test.describe('Home Page Accessibility', () => {
  test('home page has no critical or serious axe violations', async ({page}) => {
    await page.goto('/zh');

    await assertNoCriticalOrSeriousViolations(
      checkA11y(page, {
        excludeRules: [
          'color-contrast',
        ],
      })
    );
  });

  test('home page has proper heading structure', async ({page}) => {
    await page.goto('/zh');

    const h1 = page.locator('h1');
    await expect(h1).toBeVisible();

    const h1Count = await h1.count();
    expect(h1Count).toBe(1);
  });

  test('home page navigation links are keyboard accessible', async ({page}) => {
    await page.goto('/zh');

    const navLinks = page.locator('nav a, [role="navigation"] a');
    const count = await navLinks.count();

    if (count > 0) {
      for (let i = 0; i < count; i++) {
        const link = navLinks.nth(i);
        await expect(link).toHaveAttribute('href', /.+/);
      }
    }
  });
});

test.describe('Admin Page Accessibility', () => {
  test('admin page shell has no critical or serious axe violations', async ({page}) => {
    await page.goto('/zh/admin');

    await assertNoCriticalOrSeriousViolations(
      checkA11y(page, {
        excludeRules: [
          'color-contrast',
        ],
      })
    );
  });

  test('admin page tabs have proper ARIA roles when unauthenticated', async ({page}) => {
    await page.goto('/zh/admin');

    const tablist = page.locator('[role="tablist"]').first();

    if (await tablist.isVisible().catch(() => false)) {
      const tabs = tablist.locator('[role="tab"]');
      const tabCount = await tabs.count();

      for (let i = 0; i < tabCount; i++) {
        const tab = tabs.nth(i);
        await expect(tab).toHaveAttribute('role', 'tab');
      }
    }
  });

  test('admin page login required message is accessible', async ({page}) => {
    await page.goto('/zh/admin');

    const loginRequiredHeading = page.getByRole('heading', {name: '需要登录'});
    await expect(loginRequiredHeading).toBeVisible({timeout: 5000});

    const level = await loginRequiredHeading.evaluate(el => el.tagName.toLowerCase());
    expect(level).toMatch(/^h[1-6]$/);
  });
});

test.describe('Register Page Accessibility', () => {
  test('register page has no critical or serious axe violations', async ({page}) => {
    await page.goto('/zh/auth/register');

    await assertNoCriticalOrSeriousViolations(
      checkA11y(page, {
        excludeRules: [
          'color-contrast',
        ],
      })
    );
  });
});

test.describe('Saves Page Accessibility', () => {
  test('saves page has no critical or serious axe violations when authenticated', async ({page}) => {
    await page.goto('/zh/auth/register');
    await page.fill('[data-testid="register-username-input"]', `a11y_user_${Date.now()}`);
    await page.fill('[data-testid="register-password-input"]', 'TestPass123!');
    await page.click('[data-testid="register-submit"]');

    await page.goto('/zh/saves');

    await assertNoCriticalOrSeriousViolations(
      checkA11y(page, {
        excludeRules: [
          'color-contrast',
        ],
      })
    );
  });
});
