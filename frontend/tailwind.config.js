/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  darkMode: "class",
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
          // dark theme counterparts (warm near-blacks to match the milk panels)
          dbg: "#0e0d0b",
          dpanel: "#171511",
          dcard: "#1d1b16",
          dborder: "#2b2820",
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
