import { forwardToFinrag } from "@/lib/server/finrag";

export const maxDuration = 300;
export const dynamic = "force-dynamic";

/** Proxies an idempotent ingest request to the FastAPI backend. */
export function POST(request: Request) {
  return forwardToFinrag(request, "/ingest");
}
