/**
 * TrickLens design tokens: the single source for colors, type and shape,
 * shared by the web app now and the native app later.
 *
 * Three brand colors carry meaning everywhere (docs/components/frontend.md,
 * Design tokens):
 *   - Light Yellow: scores (steeze stickers, averages)
 *   - Light Azure: selection and social (active nav, following, approve)
 *   - Dark Gray Brown: ink and primary actions
 * A muted red is reserved for errors and destructive actions.
 */

export const brand = {
  yellow: '#FEF0B6',
  azure: '#BBD3E0',
  brown: '#472F26',
} as const;

export type ThemeName = 'light' | 'dark';

export interface ThemeColors {
  bg: string;
  surface: string;
  panel: string;
  raised: string;
  line: string;
  border: string;
  ink: string;
  ink2: string;
  muted: string;
  faint: string;
  primary: string;
  onPrimary: string;
  scoreBg: string;
  scoreInk: string;
  track: string;
  fill: string;
  sel: string;
  onSel: string;
  link: string;
  heroBg: string;
  heroInk: string;
  hero2: string;
  danger: string;
  dangerBg: string;
  mediaA: string;
  mediaB: string;
  figure: string;
  scrim: string;
  shadow: string;
}

export const themes: Record<ThemeName, ThemeColors> = {
  light: {
    bg: '#FFFBF0',
    surface: '#FFFFFF',
    panel: '#FBF4DF',
    raised: '#FFFFFF',
    line: 'rgba(71,47,38,0.10)',
    border: 'rgba(71,47,38,0.20)',
    ink: brand.brown,
    ink2: '#5E463C',
    muted: '#7D675C',
    faint: '#9C877B',
    primary: brand.brown,
    onPrimary: brand.yellow,
    scoreBg: brand.yellow,
    scoreInk: brand.brown,
    track: '#F1E7C9',
    fill: brand.brown,
    sel: brand.azure,
    onSel: '#2B1C16',
    link: '#2E5B74',
    heroBg: brand.yellow,
    heroInk: brand.brown,
    hero2: '#6B5245',
    danger: '#B3412C',
    dangerBg: 'rgba(179,65,44,0.08)',
    mediaA: '#F3E8C8',
    mediaB: '#D3E2EA',
    figure: '#9C877B',
    scrim: 'rgba(71,47,38,0.45)',
    shadow: '0 1px 2px rgba(71,47,38,0.06), 0 10px 28px rgba(71,47,38,0.08)',
  },
  dark: {
    bg: '#1B120E',
    surface: '#251913',
    panel: '#2E2019',
    raised: brand.brown,
    line: 'rgba(254,240,182,0.09)',
    border: 'rgba(254,240,182,0.18)',
    ink: '#FBF3DE',
    ink2: '#E6D9C5',
    muted: '#BBA996',
    faint: '#8E7B6B',
    primary: brand.yellow,
    onPrimary: brand.brown,
    scoreBg: brand.yellow,
    scoreInk: brand.brown,
    track: '#3B2A21',
    fill: brand.yellow,
    sel: brand.azure,
    onSel: '#2B1C16',
    link: brand.azure,
    heroBg: brand.brown,
    heroInk: brand.yellow,
    hero2: '#E6D9C5',
    danger: '#F09A85',
    dangerBg: 'rgba(240,154,133,0.10)',
    mediaA: '#3A2A21',
    mediaB: '#22313B',
    figure: '#8E7B6B',
    scrim: 'rgba(10,6,4,0.62)',
    shadow: '0 1px 2px rgba(0,0,0,0.3), 0 10px 28px rgba(0,0,0,0.35)',
  },
};

export const fonts = {
  display: "'Bricolage Grotesque Variable', 'Bricolage Grotesque', system-ui, sans-serif",
  body: "'Barlow', system-ui, sans-serif",
  mono: "'DM Mono', ui-monospace, monospace",
} as const;

export const radii = { sm: '8px', md: '10px', lg: '14px', xl: '16px', sheet: '22px', pill: '999px' } as const;

/** Width at which the app switches from the phone layout to the desktop layout. */
export const breakpoints = { desktop: 900 } as const;

const kebab = (s: string) => s.replace(/[A-Z0-9]/g, (c) => `-${c.toLowerCase()}`);

function declarations(t: ThemeColors): string {
  return Object.entries(t)
    .map(([k, v]) => `  --${kebab(k)}: ${v};`)
    .join('\n');
}

/**
 * CSS for both themes. Light is the default on :root; dark applies when the
 * viewer picked it (`data-theme="dark"` on <html>) or picked nothing and the
 * OS is dark. `data-theme="light"` wins over a dark OS.
 */
export function themeCss(): string {
  const shared = [
    `  --font-display: ${fonts.display};`,
    `  --font-body: ${fonts.body};`,
    `  --font-mono: ${fonts.mono};`,
    ...Object.entries(radii).map(([k, v]) => `  --radius-${k}: ${v};`),
    `  --yellow: ${brand.yellow};`,
    `  --azure: ${brand.azure};`,
    `  --brown: ${brand.brown};`,
  ].join('\n');
  const dark = `${declarations(themes.dark)}\n  color-scheme: dark;`;
  return [
    `:root {\n${shared}\n${declarations(themes.light)}\n  color-scheme: light;\n}`,
    `@media (prefers-color-scheme: dark) {\n:root:not([data-theme="light"]) {\n${dark}\n}\n}`,
    `:root[data-theme="dark"] {\n${dark}\n}`,
  ].join('\n');
}
