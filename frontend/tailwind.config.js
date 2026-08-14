/** @type {import('tailwindcss').Config} */

// Facet design language.
//
// Deliberately not the pastel-purple, heavily-rounded look that Culture Amp,
// Lattice and 15Five all converge on. This is an analytical tool that will sit
// in front of executives, so it borrows from editorial and financial software:
// ink neutrals, one calm forest-teal accent, soft cards instead of hard
// hairlines, tight type, and dense tables that respect the reader's screen.
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
        // Forest teal. Calmer than the old copper, reads as trust/growth
        // rather than boutique-agency warmth, and still holds contrast on
        // both ink-900 and white.
        teal: {
          50: '#EAF3F1',
          100: '#D3E6E1',
          200: '#A9CDC4',
          300: '#7BB2A6',
          400: '#4FA893',
          500: '#2F6F62',
          600: '#265A50',
          700: '#1E4F45',
          800: '#173B34',
          900: '#102822',
        },
        // Semantic accents for the feedback graph, kept independent of the
        // brand accent so they never fight a tenant's custom color. Internal
        // relationships read cool, external ones read warm.
        internal: '#3572B0',
        external: '#C08A2E',
        positive: '#2F8F5B',
        caution: '#C4791F',
        critical: '#C23B33',
        info: '#3572B0',
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
        DEFAULT: '7px',
        md: '9px',
        lg: '10px',
        xl: '14px',
      },
      boxShadow: {
        card: '0 1px 2px rgba(18,22,28,0.04), 0 1px 1px rgba(18,22,28,0.03)',
        lift: '0 8px 24px -8px rgba(18,22,28,0.18), 0 2px 6px rgba(18,22,28,0.06)',
        focus: '0 0 0 3px rgba(47,111,98,0.22)',
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
        'toast-in': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.32s cubic-bezier(0.2, 0.7, 0.3, 1) both',
        'ring-draw': 'ring-draw 1.1s cubic-bezier(0.3, 0.8, 0.3, 1) both',
        shimmer: 'shimmer 1.4s linear infinite',
        'toast-in': 'toast-in 0.22s ease both',
      },
    },
  },
  plugins: [],
}
