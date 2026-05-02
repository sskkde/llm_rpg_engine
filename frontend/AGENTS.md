<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

## Frontend API/proxy key points
- `frontend/lib/api.ts` should default to a same-origin relative API base (`const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? ''`).
- `frontend/next.config.ts` should use `rewrites` to forward backend API prefixes (`auth`, `saves`, `sessions`, `world`, `game`, `streaming`, `combat`, `admin`, `debug`, `media`, `dev`) to `process.env.BACKEND_API_URL || 'http://127.0.0.1:8000'`.
- `frontend/proxy.ts` must exclude the backend API prefixes from the next-intl matcher so browser API requests are not intercepted before the rewrites run.
- In public deployments, use `npm run build` then `npm run start`. Do not expose `next dev` over the public internet.
- If a public origin is added (e.g. `https://llm.nas-1.club:18080`), add it to backend CORS separately.
