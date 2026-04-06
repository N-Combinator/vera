/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        vera: {
          purple: "#7c3aed",
          dark: "#0f172a",
        },
      },
    },
  },
  plugins: [],
};
