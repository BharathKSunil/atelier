import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["atelier/web/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser },
    },
    rules: {
      "no-unused-vars": "error",
      "no-undef": "error",
      eqeqeq: ["error", "smart"], // allow == null; require === elsewhere
      "no-implicit-globals": "error",
      "no-empty": ["error", { allowEmptyCatch: true }], // intentional best-effort swallows
    },
  },
];
