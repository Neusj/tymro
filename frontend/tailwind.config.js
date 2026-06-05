/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      screens: {
        // default sm:640 md:768 lg:1024 xl:1280 2xl:1536 kept
        '3xl': '1920px', // TV / ultra-wide
      },
      fontFamily: {
        sans: ['"Hanken Grotesk"', 'system-ui', 'Segoe UI', 'sans-serif'],
        display: ['"Bricolage Grotesque"', '"Hanken Grotesk"', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          // base (kept for backwards compatibility)
          black: '#09090b',
          red: '#dc2626',
          white: '#fafafa',
          orange: '#f97316',
          blue: '#2563eb',
          soft: '#18181b',
          line: '#27272a',
          muted: '#a1a1aa',
          // new elevation scale
          ink: '#060608', // deepest background
          panel: '#101013', // raised panel
          elevated: '#1c1c20', // hovered / floating
          hairline: '#2e2e33', // brighter divider
          dim: '#71717a', // tertiary text
        },
        // semantic (additive — default tailwind emerald/amber still available)
        success: { DEFAULT: '#10b981', soft: 'rgba(16,185,129,0.12)', line: 'rgba(16,185,129,0.4)' },
        warning: { DEFAULT: '#f59e0b', soft: 'rgba(245,158,11,0.12)', line: 'rgba(245,158,11,0.4)' },
        danger: { DEFAULT: '#dc2626', soft: 'rgba(220,38,38,0.12)', line: 'rgba(220,38,38,0.4)' },
        info: { DEFAULT: '#2563eb', soft: 'rgba(37,99,235,0.12)', line: 'rgba(37,99,235,0.4)' },
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(255,255,255,0.05), 0 20px 60px rgba(0,0,0,0.35)',
        soft: '0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.25)',
        float: '0 12px 40px rgba(0,0,0,0.5)',
        focus: '0 0 0 3px rgba(37,99,235,0.35)',
      },
      borderRadius: {
        xl2: '1.25rem',
      },
      maxWidth: {
        app: '1600px', // caps content on TV / ultra-wide
      },
      transitionTimingFunction: {
        snap: 'cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        'fade-rise': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'scale-in': {
          '0%': { opacity: '0', transform: 'scale(0.97)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
      animation: {
        'fade-rise': 'fade-rise 0.4s cubic-bezier(0.22, 1, 0.36, 1) both',
        'scale-in': 'scale-in 0.2s cubic-bezier(0.22, 1, 0.36, 1) both',
      },
    },
  },
  plugins: [],
}
