import type {Page, Locator} from '@playwright/test';

const MIN_TOUCH_TARGET_SIZE = 44;

export interface TouchTargetCheck {
  element: string;
  width: number;
  height: number;
  passed: boolean;
}

export async function assertMinTouchTarget(
  locator: Locator,
  minSize = MIN_TOUCH_TARGET_SIZE
): Promise<TouchTargetCheck> {
  const boundingBox = await locator.boundingBox();

  if (!boundingBox) {
    throw new Error('Element not found or not visible');
  }

  const check: TouchTargetCheck = {
    element: await getElementDescription(locator),
    width: boundingBox.width,
    height: boundingBox.height,
    passed: boundingBox.width >= minSize && boundingBox.height >= minSize,
  };

  if (!check.passed) {
    throw new Error(
      `Touch target too small: ${check.element} is ${check.width}px x ${check.height}px (min: ${minSize}px x ${minSize}px)`
    );
  }

  return check;
}

export async function checkTouchTargets(
  page: Page,
  selector: string,
  minSize = MIN_TOUCH_TARGET_SIZE
): Promise<TouchTargetCheck[]> {
  const elements = await page.locator(selector).all();
  const results: TouchTargetCheck[] = [];

  for (const element of elements) {
    const boundingBox = await element.boundingBox();
    if (boundingBox) {
      results.push({
        element: await getElementDescription(element),
        width: boundingBox.width,
        height: boundingBox.height,
        passed:
          boundingBox.width >= minSize && boundingBox.height >= minSize,
      });
    }
  }

  return results;
}

export function getFailedTouchTargets(
  results: TouchTargetCheck[]
): TouchTargetCheck[] {
  return results.filter(r => !r.passed);
}

async function getElementDescription(locator: Locator): Promise<string> {
  const tagName = await locator.evaluate(el => el.tagName.toLowerCase());
  const text = await locator.textContent().catch(() => '');
  const testId = await locator.getAttribute('data-testid').catch(() => '');

  if (testId) return `<${tagName} data-testid="${testId}">`;
  if (text && text.length <= 30) return `<${tagName}>${text}</${tagName}>`;
  return `<${tagName}>`;
}
