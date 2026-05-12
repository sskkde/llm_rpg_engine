/**
 * Test setup file with browser API mocks for JSDOM environment
 * 
 * This file provides mocks for browser APIs that are not available in JSDOM:
 * - matchMedia: CSS media query matching
 * - ResizeObserver: Element resize observation
 * - IntersectionObserver: Element intersection observation
 * - scrollTo: Window scroll behavior
 */

// Mock matchMedia for responsive design tests
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(), // deprecated
    removeListener: jest.fn(), // deprecated
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
});

// Mock ResizeObserver for component resize detection
global.ResizeObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}));

// Mock IntersectionObserver for visibility detection
global.IntersectionObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
  root: null,
  rootMargin: '',
  thresholds: [],
}));

// Mock scrollTo for scroll behavior tests
window.scrollTo = jest.fn();

// Mock scrollIntoView for element scrolling
Element.prototype.scrollIntoView = jest.fn();
