/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./src/**/*.{vue,js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // We can define custom theme colors matching the demo.html styles
        primary: '#0b0f19',
        secondary: '#111827',
        tertiary: '#1f2937',
      }
    },
  },
  plugins: [],
}
