// Unit tests for the 2D-fallback trigger: prefers-reduced-motion OR mobile UA → table instead
// of Canvas. Stubs matchMedia/navigator directly (repo convention, see theme-context.test.tsx)
// rather than mounting anything from react-three-fiber.
import { afterEach, describe, expect, test, vi } from 'vitest'
import { isMobileUserAgent, prefersReducedMotion, shouldUseFallback } from './use-3d-fallback'

function stubMatchMedia(reduced: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('reduce') ? reduced : false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
    onchange: null,
  }))
}

function stubUserAgent(ua: string) {
  vi.stubGlobal('navigator', { userAgent: ua })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('prefersReducedMotion', () => {
  test('reflects matchMedia(prefers-reduced-motion: reduce)', () => {
    stubMatchMedia(true)
    expect(prefersReducedMotion()).toBe(true)
  })

  test('false when the OS has no reduced-motion preference', () => {
    stubMatchMedia(false)
    expect(prefersReducedMotion()).toBe(false)
  })
})

describe('isMobileUserAgent', () => {
  test('detects an iPhone UA', () => {
    stubUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')
    expect(isMobileUserAgent()).toBe(true)
  })

  test('detects an Android UA', () => {
    stubUserAgent('Mozilla/5.0 (Linux; Android 14)')
    expect(isMobileUserAgent()).toBe(true)
  })

  test('a desktop UA is not mobile', () => {
    stubUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')
    expect(isMobileUserAgent()).toBe(false)
  })
})

describe('shouldUseFallback', () => {
  test('true when reduced-motion is preferred, even on desktop UA', () => {
    stubMatchMedia(true)
    stubUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')
    expect(shouldUseFallback()).toBe(true)
  })

  test('true on a mobile UA, even without reduced-motion', () => {
    stubMatchMedia(false)
    stubUserAgent('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')
    expect(shouldUseFallback()).toBe(true)
  })

  test('false when neither condition holds', () => {
    stubMatchMedia(false)
    stubUserAgent('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')
    expect(shouldUseFallback()).toBe(false)
  })
})
