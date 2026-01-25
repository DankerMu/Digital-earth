import type { Config } from 'tailwindcss';

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      zIndex: {
        '60': '60',
      },
    },
  },
  plugins: [],
} satisfies Config;
