/** @type {import('tailwindcss').Config} */

// Facet design language.
//
// Deliberately not the pastel-purple, heavily-rounded look that Culture Amp,
// Lattice and 15Five all converge on. This is an analytical tool that will sit
// in front of executives, so it borrows from editorial and financial software:
// ink neutrals, one warm metallic accent, hairline borders instead of drop
// shadows, tight type, and dense tables that respect the reader's screen.
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#F6F7F9',
          100: '#ECEEF1',
          200: '#DDE1E6',
          300: '#C2C8D0',
          400: '#8A93A0',
          500: '#5A6472',
          600: '#39414D',
          700: '#252C36',
          800: '#181D25',
          900: '#12161C',
          950: '#0B0E12',
        },
        // Copper. Warm, uncommon in this category, and legible on both
        // ink-900 and white, which a mid-tone purple is not.
        copper: {
          50: '#FBF3EF',
          100: '#F4E1D7',
          200: '#E7C2AF',
          300: '#D79C7F',
          400: '#C67B57',
          500: '#B4633A',
          600: '#9A5130',
          700: '#7C4027',
          800: '#5E3120',
          900: '#41231A',
        },
        // Semantic accents for the feedback graph. Internal relationships read
        // cool, external ones read warm, so the split is legible before the
        // legend is.
        internal: '#3D7A8C',
        external: '#B4633A',
        positive: '#2F7D5B',
        caution: '#B4863A',
        critical: '#A63D3D',
      },
      fontFamily: {
        sans: [
          'Inter',
          'Inter Tight',
          '-apple-system',
          'Segoe UI Variable Display',
          'Segoe UI',
          'system-ui',
          'sans-serif',
        ],
        mono: ['Cascadia Code', 'JetBrains Mono', 'Consolas', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.04em' }],
        xs: ['0.75rem', { lineHeight: '1.1rem' }],
        sm: ['0.8125rem', { lineHeight: '1.25rem' }],
        base: ['0.875rem', { lineHeight: '1.4rem' }],
        lg: ['1rem', { lineHeight: '1.5rem' }],
        xl: ['1.125rem', { lineHeight: '1.6rem', letterSpacing: '-0.01em' }],
        '2xl': ['1.375rem', { lineHeight: '1.75rem', letterSpacing: '-0.018em' }],
        '3xl': ['1.75rem', { lineHeight: '2.1rem', letterSpacing: '-0.022em' }],
        '4xl': ['2.25rem', { lineHeight: '2.5rem', letterSpacing: '-0.028em' }],
        '5xl': ['3rem', { lineHeight: '3.1rem', letterSpacing: '-0.032em' }],
      },
      borderRadius: {
        // Restrained. Large radii read consumer; this product is sold to
        // people who buy Qualtrics.
        DEFAULT: '4px',
        md: '6px',
        lg: '8px',
        xl: '12px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(18,22,28,0.04), 0 1px 1px rgba(18,22,28,0.03)',
        lift: '0 8px 24px -8px rgba(18,22,28,0.18), 0 2px 6px rgba(18,22,28,0.06)',
        focus: '0 0 0 3px rgba(180,99,58,0.22)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'ring-draw': {
          '0%': { strokeDashoffset: 'var(--dash)' },
          '100%': { strokeDashoffset: 'var(--offset)' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-460px 0' },
          '100%': { backgroundPosition: '460px 0' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.32s cubic-bezier(0.2, 0.7, 0.3, 1) both',
        'ring-draw': 'ring-draw 1.1s cubic-bezier(0.3, 0.8, 0.3, 1) both',
        shimmer: 'shimmer 1.4s linear infinite',
      },
    },
  },
  plugins: [],
}
