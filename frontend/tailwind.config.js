/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#08090b',
          900: '#0b0c0e',
          850: '#0f1013',
          800: '#121317',
          750: '#16171c',
          700: '#1a1c21',
          650: '#1f2127',
          600: '#26282e',
          500: '#33363e',
          400: '#4a4e58',
          300: '#6b7080',
          200: '#9499a6',
          100: '#c4c8d2',
          50: '#e8eaef',
        },
        amber: {
          300: '#ffd27a',
          400: '#ffbf47',
          500: '#ffab1a',
          600: '#e6930a',
          700: '#b37000',
        },
      },
      fontFamily: {
        sans: ['Inter', '"Segoe UI Variable"', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', '"Cascadia Code"', 'Consolas', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', '14px'],
      },
      boxShadow: {
        panel: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -12px rgba(0,0,0,0.6)',
        pop: '0 20px 50px -12px rgba(0,0,0,0.75)',
      },
    },
  },
  plugins: [],
};
