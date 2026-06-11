/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./app/**/*.{js,jsx}", "./components/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        // IBM Carbon-inspired palette
        carbon: {
          bg: "#f5f6f8",
          panel: "#ffffff",
          border: "#eaeaec",
          text: "#161616",
          subtle: "#6b6b76",
          blue: "#0f62fe",
          blueHover: "#0353e9",
          green: "#24a148",
          red: "#da1e28",
          yellow: "#f1c21b",
          gray100: "#161616",
          gray70: "#525252",
        },
      },
      fontFamily: {
        sans: ["'IBM Plex Sans'", "system-ui", "Segoe UI", "Arial", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
