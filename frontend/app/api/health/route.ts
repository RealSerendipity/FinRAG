import { forwardToFinrag } from "@/lib/server/finrag";

export const maxDuration = 300;
export const dynamic = "force-dynamic";

/** Proxies the public health check to the FastAPI backend. */
export function GET(request: Request) {
  return forwardToFinrag(request, "/health");
}
