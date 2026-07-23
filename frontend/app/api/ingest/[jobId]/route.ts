import { forwardToFinrag } from "@/lib/server/finrag";

const JOB_ID = /^[A-Za-z0-9-]{1,64}$/;

export const maxDuration = 300;
export const dynamic = "force-dynamic";

/** Proxies a validated ingest status request to the FastAPI backend. */
export async function GET(
  request: Request,
  context: { params: Promise<{ jobId: string }> },
) {
  const { jobId } = await context.params;
  if (!JOB_ID.test(jobId)) {
    return Response.json(
      { code: "invalid_job_id", error: "invalid job id" },
      { status: 400 },
    );
  }
  return forwardToFinrag(request, `/ingest/${jobId}`);
}
