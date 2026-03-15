module.exports = {
  content: [
    './index.html',
    './src/**/*.{html,js,svelte,ts}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'Montserrat', 'ui-sans-serif', 'system-ui'],
      },
      colors: {
        primary: '#1c7ed6',
        accent: '#74c0fc',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
    require('@tailwindcss/typography'),
  ],
};
