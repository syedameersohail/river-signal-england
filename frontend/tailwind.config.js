/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "IBM Plex Sans", "Source Sans Pro", "Arial", "sans-serif"],
        mono: [
          "IBM Plex Mono",
          "ui-monospace",
          "SFMono-Regular",
          "Consolas",
          "monospace",
        ],
      },
      colors: {
        ink: "#111827",
        slatecopy: "#4b5563",
        riverblue: "#0D7377",
        "riverblue-dark": "#09575a",
        paper: "#F8F9FA",
      },
      boxShadow: {
        panel: "0 18px 60px rgba(17, 24, 39, 0.16)",
      },
    },
  },
  plugins: [],
};
