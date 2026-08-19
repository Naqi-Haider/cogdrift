/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        nh: {
          bg: '#f2f5f2',
          card: '#ffffff',
          dark: '#1e2923',
          darker: '#141c18',
          green: {
            DEFAULT: '#36654b',
            deep: '#234936',
            hover: '#2d5740',
            light: '#e8f2ec',
            subtle: '#f0f6f2',
            accent: '#52796f',
            mint: '#6ba381',
            ring: '#2d5a43'
          },
          text: {
            main: '#1b2620',
            muted: '#687a70',
            light: '#8fa095'
          }
        }
      },
      borderRadius: {
        '3xl': '1.5rem',
        '4xl': '2rem'
      },
      boxShadow: {
        'nh-card': '0 4px 20px -2px rgba(45, 90, 67, 0.05), 0 2px 6px -1px rgba(0, 0, 0, 0.02)',
        'nh-lift': '0 10px 25px -3px rgba(45, 90, 67, 0.1), 0 4px 10px -2px rgba(0, 0, 0, 0.04)'
      }
    },
  },
  plugins: [],
}
