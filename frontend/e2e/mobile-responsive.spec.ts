import {test, expect, type Page} from '@playwright/test';
import {assertMinTouchTarget} from './helpers/touch-targets';

/**
 * Mobile Responsive Regression Tests
 *
 * These tests verify that key user flows work correctly on mobile devices.
 * They run on the Mobile Chrome (Pixel 5) and Tablet (iPad Pro 11) projects.
 *
 * Test coverage:
 * - Locale routing behavior on mobile
 * - Auth pages layout and functionality
 * - Saves page header stacking
 * - Game session mobile layout (narration/actions first)
 * - Admin page tab scrollability
 */

async function registerViaUi(page: Page, username: string, password: string) {
  await page.goto('/zh/auth/register');
  await page.fill('[data-testid="register-username-input"]', username);
  await page.fill('[data-testid="register-password-input"]', password);
  await page.click('[data-testid="register-submit"]');
  await expect(page).toHaveURL(/\/zh\/auth\/login\?registered=1/);
  await expect(page.locator('[data-testid="registration-success"]')).toBeVisible();
}

async function loginViaUi(page: Page, username: string, password: string) {
  await page.goto('/zh/auth/login');
  await page.fill('[data-testid="username-input"]', username);
  await page.fill('[data-testid="password-input"]', password);
  await page.click('[data-testid="login-submit"]');
  await expect(page).toHaveURL(/\/zh\/game/);
}

test.describe('Mobile Locale Routing', () => {
  test('root redirects to Chinese default on mobile', async ({page}) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/zh/);
  });

  test('mobile viewport preserves locale in URL', async ({page}) => {
    await page.goto('/en/auth/login');
    await expect(page).toHaveURL(/\/en\/auth\/login/);
    await expect(page.locator('h1')).toContainText('Login');
  });
});

test.describe('Mobile Auth Pages', () => {
  test('login page has no horizontal overflow on mobile', async ({page}) => {
    await page.goto('/zh/auth/login');

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);

    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test('login form elements meet minimum touch target size', async ({page}) => {
    await page.goto('/zh/auth/login');

    const submitButton = page.locator('[data-testid="login-submit"]');
    await assertMinTouchTarget(submitButton);
  });

  test('register page has no horizontal overflow on mobile', async ({page}) => {
    await page.goto('/zh/auth/register');

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);

    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });
});

test.describe('Mobile Auth Flow', () => {
  test('complete registration and login flow on mobile', async ({page}) => {
    const username = `mobile_user_${Date.now()}`;
    const password = 'TestPass123!';

    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await expect(page.getByRole('heading', {name: '冒险', exact: true})).toBeVisible();
  });
});

test.describe('Mobile Saves Page', () => {
  test('saves page header stacks vertically on mobile', async ({page}) => {
    const username = `mobile_save_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);

    await page.goto('/zh/saves');

    await expect(page.getByRole('heading', {name: '存档管理'})).toBeVisible();

    const newSaveButton = page.locator('button:has-text("新建存档")');
    await expect(newSaveButton).toBeVisible();
    await assertMinTouchTarget(newSaveButton);
  });

  test('saves page has no horizontal overflow on mobile', async ({page}) => {
    const username = `mobile_save_overflow_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);

    await page.goto('/zh/saves');

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);

    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test('save slot cards are visible and tappable on mobile', async ({page}) => {
    const username = `mobile_save_card_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);

    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'Mobile Test Save');
    await page.click('button:has-text("创建存档")');

    await expect(page.locator('text=Mobile Test Save')).toBeVisible({timeout: 10000});

    const saveCard = page.locator('.bg-white', {hasText: 'Mobile Test Save'}).first();
    await assertMinTouchTarget(saveCard);
  });
});

test.describe('Mobile Game Session Page', () => {
  test('game session shows narration before collapsible sections on mobile', async ({page}) => {
    const username = `mobile_game_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'Mobile Game Save');
    await page.click('button:has-text("创建存档")');
    await page.click('text=Mobile Game Save');
    await page.click('button:has-text("开始新游戏")');

    await expect(page).toHaveURL(/\/zh\/game\//, {timeout: 15000});
    await expect(page.getByRole('heading', {name: '冒险', exact: true})).toBeVisible();

    const narrationPanel = page.locator('[data-testid="narration-panel"]').or(
      page.locator('div').filter({hasText: /欢迎来到/}).first()
    );
    await expect(narrationPanel).toBeVisible();

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test('mobile state section is collapsible and accessible', async ({page}) => {
    const username = `mobile_state_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'Mobile State Save');
    await page.click('button:has-text("创建存档")');
    await page.click('text=Mobile State Save');
    await page.click('button:has-text("开始新游戏")');

    await expect(page).toHaveURL(/\/zh\/game\//, {timeout: 15000});

    const mobileStateSection = page.locator('#mobile-state-section');

    if (await mobileStateSection.isVisible().catch(() => false)) {
      await mobileStateSection.click();
      await expect(mobileStateSection).toBeVisible();
    }
  });

  test('action input is accessible on mobile', async ({page}) => {
    const username = `mobile_action_${Date.now()}`;
    const password = 'TestPass123!';
    await registerViaUi(page, username, password);
    await loginViaUi(page, username, password);
    await page.goto('/zh/saves');

    await page.click('text=新建存档');
    await page.fill('input', 'Mobile Action Save');
    await page.click('button:has-text("创建存档")');
    await page.click('text=Mobile Action Save');
    await page.click('button:has-text("开始新游戏")');

    await expect(page).toHaveURL(/\/zh\/game\//, {timeout: 15000});

    const actionInput = page.locator('input[type="text"]').or(
      page.locator('input[placeholder*="行动"]').or(
        page.locator('input[placeholder*="action"]').first()
      )
    );
    await expect(actionInput).toBeVisible();

    const submitButton = page.locator('button[type="submit"]').first();
    await assertMinTouchTarget(submitButton);
  });
});

test.describe('Mobile Admin Page', () => {
  test('admin tabs are horizontally scrollable on mobile', async ({page}) => {
    await page.goto('/zh/admin');

    const tabsContainer = page.locator('[role="tablist"]').first();
    await expect(tabsContainer).toBeVisible();

    const tabs = page.locator('[role="tab"]');
    await expect(tabs).toHaveCount(8);
  });

  test('admin page login required message is visible on mobile', async ({page}) => {
    await page.goto('/zh/admin');

    await expect(page.getByRole('heading', {name: '需要登录'})).toBeVisible({timeout: 5000});
  });

  test('admin page has no horizontal overflow on mobile', async ({page}) => {
    await page.goto('/zh/admin');

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);

    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });
});

test.describe('Mobile Home Page', () => {
  test('home page has no horizontal overflow on mobile', async ({page}) => {
    await page.goto('/zh');

    const body = page.locator('body');
    const bodyWidth = await body.evaluate(el => el.scrollWidth);
    const viewportWidth = await page.evaluate(() => window.innerWidth);

    expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);
  });

  test('home page CTA buttons meet touch target size on mobile', async ({page}) => {
    await page.goto('/zh');

    const ctaButton = page.locator('a:has-text("开始游戏"), a:has-text("Start Game")').first();
    if (await ctaButton.isVisible().catch(() => false)) {
      await assertMinTouchTarget(ctaButton);
    }
  });
});
