/** Filters accepted by the cited RAG endpoint. */
export interface RagRequest {
  question: string;
  ticker?: string | null;
  year?: number | null;
  period?: string | null;
  top_k?: number;
}

/** One source quote returned with a RAG answer. */
export interface Citation {
  chunk_id: number;
  quote: string;
  verified: boolean;
}

/** Token totals accumulated across every model call in a request. */
export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  calls: number;
  models?: Record<
    string,
    {
      input_tokens: number;
      output_tokens: number;
    }
  >;
}

/** The payload carried by the RAG stream's `answer` event. */
export interface RagAnswer {
  text: string;
  citations: Citation[];
  usage: TokenUsage;
  cost_usd: number;
  cost_estimated: boolean;
  latency_ms: number;
  trace_url: string | null;
}

/** Input accepted by the multi-step agent endpoint. */
export interface AgentRequest {
  question: string;
  max_steps?: number;
}

/** One reasoning/tool iteration returned by the agent endpoint. */
export interface AgentStep {
  thought: string;
  action: string | null;
  action_input: Record<string, unknown> | null;
  observation: string | null;
}

/** The complete multi-step agent response. */
export interface AgentAnswer {
  answer: string;
  steps: AgentStep[];
  tools_used: string[];
  stopped: string;
  usage: TokenUsage;
  cost_usd: number;
  cost_estimated: boolean;
  latency_ms: number;
  trace_url: string | null;
}

/** Input accepted by the persistent SEC filing ingest endpoint. */
export interface IngestRequest {
  tickers: string[];
  form_type?: string;
  year?: number | null;
  period?: string | null;
}

/** Initial response after an ingest batch has been queued. */
export interface IngestSubmission {
  job_id: string;
  status: "queued";
  poll: string;
}

export type IngestItemStatus =
  | "queued"
  | "running"
  | "retrying"
  | "done"
  | "error";

/** Public progress for one ticker in an ingest batch. */
export interface IngestItem {
  id: string;
  ticker: string;
  status: IngestItemStatus;
  attempts: number;
}

/** Successful or failed terminal output for one ticker. */
export type IngestResult =
  | {
      ticker: string;
      chunks: number;
      elapsed_s: number | null;
      error?: never;
    }
  | {
      ticker: string;
      error: string;
      elapsed_s: number | null;
      chunks?: never;
    };

/** Aggregate state returned while polling one persistent ingest batch. */
export interface IngestStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "error";
  items: IngestItem[];
  results: IngestResult[];
}

/** Public health response exposed through the frontend proxy. */
export interface HealthStatus {
  status: string;
  tracing: boolean;
}

/** FastAPI validation detail for one invalid request field. */
export interface ValidationErrorDetail {
  type: string;
  loc: Array<string | number>;
  msg: string;
  input: unknown;
  ctx?: Record<string, unknown>;
  url?: string;
}

/** Structured error detail used by queue and idempotency failures. */
export interface StructuredApiError {
  code: string;
  error: string;
  job_id?: string;
  retryable?: boolean;
  retry?: string;
}

/** Error JSON emitted by SSE handlers or standard FastAPI responses. */
export type ApiError =
  | { code: string; error: string }
  | { detail: string }
  | { detail: StructuredApiError }
  | { detail: ValidationErrorDetail[] };
