/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        wos: {
          bg: "#ffffff",
          panel: "#faf6ee",
          border: "#e7dfd2",
          accent: "#161616",
          accent2: "#000000",
          ok: "#166534",
        },
      },
      fontFamily: {
        sans: ["IBM Plex Sans", "system-ui", "-apple-system", "sans-serif"],
        mono: ["IBM Plex Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
