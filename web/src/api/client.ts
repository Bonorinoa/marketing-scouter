// Typed client generated from the LIVE OpenAPI on :8710 (`npm run gen:api`).
// openapi-fetch only accepts paths present in schema.d.ts, so chrome cannot invent routes
// (the API exposes no outbound-sharing or timed-send route, so none can be called).
import createClient from "openapi-fetch";
import type { paths } from "./schema";

export const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";
export const api = createClient<paths>({ baseUrl: BASE, fetch: (r: Request) => globalThis.fetch(r) });
