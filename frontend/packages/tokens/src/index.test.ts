import { describe, expect, it } from 'vitest';
import { brand, themeCss, themes } from './index.ts';

describe('tokens', () => {
  it('defines the same token names in both themes', () => {
    expect(Object.keys(themes.dark).sort()).toEqual(Object.keys(themes.light).sort());
  });

  it('keeps the brand colors as the primary action in each theme', () => {
    expect(themes.light.primary).toBe(brand.brown);
    expect(themes.dark.primary).toBe(brand.yellow);
  });

  it('emits light on :root and dark for both the OS setting and the explicit choice', () => {
    const css = themeCss();
    expect(css).toContain(':root {');
    expect(css).toContain('--on-primary: #FEF0B6;');
    expect(css).toContain(':root:not([data-theme="light"])');
    expect(css).toContain(':root[data-theme="dark"]');
  });
});
