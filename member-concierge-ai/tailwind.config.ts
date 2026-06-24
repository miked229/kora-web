import type { Config } from "tailwindcss";

/**
 * Paleta inspirada en resorts de lujo del Caribe:
 * azul océano, turquesa, blanco arena y dorado.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        ocean: {
          50: "#eef7fb",
          100: "#d4ecf5",
          200: "#a8d8ea",
          300: "#6fbdd9",
          400: "#3a9cc2",
          500: "#1f7da6",
          600: "#176488",
          700: "#15506e",
          800: "#16435b",
          900: "#0e2e40", // azul océano profundo
        },
        turquoise: {
          50: "#e8fbf8",
          100: "#c4f5ee",
          200: "#8eebe0",
          300: "#57d6c8",
          400: "#26c4b8",
          500: "#0fa99e", // turquesa principal
          600: "#0a877f",
          700: "#0c6c66",
          800: "#0e5653",
          900: "#0f4745",
        },
        sand: {
          50: "#fdfbf6",
          100: "#faf4e8", // blanco arena
          200: "#f3e9d2",
          300: "#e9d8b4",
          400: "#dcc28d",
        },
        gold: {
          300: "#e8cf8f",
          400: "#d8b65f",
          500: "#c79a35", // dorado premium
          600: "#a87d24",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        serif: ["var(--font-playfair)", "Georgia", "serif"],
      },
      boxShadow: {
        premium: "0 10px 40px -12px rgba(14, 46, 64, 0.35)",
        glow: "0 0 0 1px rgba(199, 154, 53, 0.4), 0 8px 30px -8px rgba(15, 169, 158, 0.45)",
      },
      backgroundImage: {
        "ocean-gradient": "linear-gradient(135deg, #0e2e40 0%, #0fa99e 100%)",
        "sunset-gradient": "linear-gradient(135deg, #0fa99e 0%, #c79a35 100%)",
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.5rem",
      },
    },
  },
  plugins: [],
};

export default config;
