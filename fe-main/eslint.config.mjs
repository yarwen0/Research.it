import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

// Next 16 removed `next lint`, so linting runs through the ESLint CLI. As of
// eslint-config-next 16 the shared config is already flat, so it composes
// directly — no FlatCompat shim.
export default [
  {
    ignores: [
      ".next/**",
      "out/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      // Generated from the backend's OpenAPI schema.
      "lib/api-types.ts",
    ],
  },
  ...nextCoreWebVitals,
  {
    // eslint-config-next 16 turns on the React Compiler rule set, which flags
    // 24 pre-existing issues — mostly ref access during render and setState
    // inside effects, concentrated in the two graph renderers.
    //
    // A ratchet, not a dismissal: they stay visible as warnings so the upgrade
    // could land without either a silent downgrade or a rewrite of components
    // this change has no other reason to touch. Move each back to "error" as
    // it is fixed.
    rules: {
      "react-hooks/refs": "warn",
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/immutability": "warn",
      "react-hooks/incompatible-library": "warn",
      "react-hooks/purity": "warn",
      "react-hooks/static-components": "warn",
      "react-hooks/error-boundaries": "warn",
    },
  },
];
