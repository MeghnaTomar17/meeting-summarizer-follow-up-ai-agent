# Frontend

## Requirements and setup

Use Node.js 20.19+ or 22.12+ and npm. From this directory, install the pinned
dependencies with:

```sh
npm ci
```

Copy `.env.example` to `.env.local` when you need to change the Gateway URL.
`VITE_GATEWAY_API_URL` is the API base consumed by browser code and defaults to
`/api/v1`. For local development, Vite proxies `/api` to
`VITE_DEV_GATEWAY_PROXY_TARGET`, which defaults to `http://localhost:8000`.
Do not put credentials or secrets in Vite environment variables; `VITE_` values
are included in client-side code.

Run the development server with:

```sh
npm run dev
```

The Gateway must be running at the configured proxy target. Deployments must
serve the frontend and `/api` from one origin or configure Gateway CORS for the
frontend origin; this repository does not currently configure Gateway CORS.

## Checks

```sh
npm test
npm run typecheck
npm run build
```

## Authentication limitations

Access and refresh tokens are held in JavaScript memory only; passwords and
tokens are never written to local or session storage. A page reload clears the
session and requires another sign-in. When an authenticated request receives a
401, the client uses the Gateway's rotating refresh endpoint once and retries
the request. If refresh fails, client authentication is cleared. Logout revokes
the refresh token when the Gateway is reachable, but the Gateway does not
revoke already-issued access JWTs; they remain valid until their configured
expiry. Signup creates an account but does not issue tokens, so the user signs
in afterward.

The authenticated pages outside Login and Signup are clearly labeled
placeholders for later Phase 14 blocks.
