# Pod Knowledge Engine - Frontend

This is the frontend for the Pod Knowledge Engine project — a React + TypeScript SPA built with Vite and Tailwind v4.

## Requirements

- Node 20+
- Yarn

> This project uses Yarn. Do not use `npm install` — it will create a `package-lock.json` and conflict with `yarn.lock`.

## Setup

### 1. Install Dependencies

```bash
cd frontend
yarn
```

### 2. Run the Dev Server

```bash
yarn dev
```

> App available at http://localhost:3000

The Vite dev server proxies `/api/*` requests to `http://localhost:3001`. The backend must be running for any data to load — see `backend/README.md`.

## Environment

Copy `.env.example` to `.env` and adjust as needed.

```bash
cp .env.example .env
```

| Variable       | Default   | Description                                                                                                                                                             |
| -------------- | --------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VITE_API_URL` | *(empty)* | Backend URL. Leave unset in local dev - Vite proxy handles `/api/*` routing automatically. Set to your backend URL for production builds e.g. `https://your-domain.com` |
| `VITE_PORT`    | `3000`    | Dev server port                                                                                                                                                         |


## Useful Commands

```bash
yarn dev        # development server with HMR
yarn build      # TypeScript check + production build
yarn lint       # ESLint
```

## Key Tech

- **React 19** + **TypeScript**
- **Vite 8** with `@tailwindcss/vite` — no `postcss.config.js` needed
- **TanStack Query v5** — data fetching and cache management
- **React Router v7** — client-side routing
- **shadcn/ui** — component library; add components with `yarn dlx shadcn add <component>`
- **axios** — API client (`src/api/client.ts`)

## Project Structure

```
src/
  api/           # axios client and TypeScript types for all API responses
  components/    # shared UI components including shadcn/ui components in ui/
  hooks/         # data-fetching and SSE hooks
  lib/           # utilities (episode formatting, text helpers)
  pages/         # one component per route
```

## Notes

- Path alias `@/*` resolves to `src/*` — use `@/components/Foo` not relative paths
- SSE hooks in `src/hooks/` stream ingestion pipeline status in real time
- Chat state is session-scoped and held in memory — refreshing the page starts a new session