import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        sand: "#f5f0e8",
        clay: "#be7b52",
        ink: "#1b1a18",
        sage: "#87957a",
        mist: "#e4e0d8"
      },
      fontFamily: {
        display: ["Georgia", "serif"],
        body: ["Trebuchet MS", "sans-serif"]
      },
      boxShadow: {
        panel: "0 24px 60px rgba(27, 26, 24, 0.12)"
      }
    }
  },
  plugins: []
};

export default config;

