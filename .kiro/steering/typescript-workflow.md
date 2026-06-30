---
inclusion: fileMatch
fileMatchPattern: "**/*.ts,**/*.tsx,**/tsconfig.json,**/package.json"
---

# TypeScript & npm Workflow

## Tools Available

- `npm` — package manager (installed globally)
- `tsc` — TypeScript compiler (installed globally)

## Conventions

- Use `tsc` for compilation. The frontend tsconfig is at `ui/frontend/tsconfig.json`.
- After editing `.ts` files in `ui/frontend/`, compile with: `tsc -p ui/frontend/tsconfig.json`
- Use `npm` for dependency management when package.json exists.
- Prefer exact versions in package.json (no ^ or ~ ranges).

## Commands

- Install deps: `npm install`
- Compile TS: `tsc -p ui/frontend/tsconfig.json`
- Type-check only: `tsc --noEmit -p ui/frontend/tsconfig.json`
- Run backend: `uvicorn ui.backend.main:app --reload --port 8000`

## Style

- Use strict TypeScript (`"strict": true`).
- Use ES2020+ features (async/await, optional chaining, nullish coalescing).
- Prefer interfaces over type aliases for object shapes.
- Use camelCase for variables/functions, PascalCase for interfaces/classes.
