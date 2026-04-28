const API_BASE = '/api';

export interface Domain {
  name: string;
  description: string;
}

export interface DomainsResponse {
  domains: Domain[];
}

export async function fetchDomains(): Promise<Domain[]> {
  const res = await fetch(`${API_BASE}/domains`);
  if (!res.ok) throw new Error('Failed to fetch domains');
  const body: DomainsResponse = await res.json();
  return body.domains;
}

export interface Todo {
  id: string;
  text: string;
  status: 'pending' | 'in_progress' | 'completed';
}

export interface PlanSnapshot {
  todos: Todo[];
  updated_at: string | null;
}

/**
 * Fetch the latest planner todo snapshot for (user_id, thread_id).
 * The `X-Domain` header picks the per-domain database on the backend.
 * Always resolves with a snapshot (empty list when no plan yet) — never 404.
 */
export async function fetchPlan(
  userId: string,
  threadId: string,
  domain: string,
): Promise<PlanSnapshot> {
  const params = new URLSearchParams({ user_id: userId, thread_id: threadId });
  const res = await fetch(`${API_BASE}/plans?${params.toString()}`, {
    headers: { 'X-Domain': domain },
  });
  if (!res.ok) throw new Error(`Failed to fetch plan (HTTP ${res.status})`);
  return (await res.json()) as PlanSnapshot;
}

export interface HealthResponse {
  mongo: string;
  db: string;
  domain: string;
  llm_model: string;
  ts: string;
}

/**
 * GET /api/health — used by the Header's model badge to read the backend's
 * configured LLM_MODEL so the label stays aligned without exposing a selector.
 */
export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Failed to fetch health (HTTP ${res.status})`);
  return (await res.json()) as HealthResponse;
}

export interface ChatRequest {
  user_id: string;
  thread_id?: string;
  message: string;
}

// Callbacks fire as SSE frames arrive. The stream contract is defined in
// server/app.py: `event: token`, `event: done`, `event: error`.
export interface StreamHandlers {
  onToken: (token: string) => void;
  onDone: () => void;
  onError: (detail: string) => void;
}

/**
 * POST /api/chat as a streaming fetch. Parses SSE frames on the fly.
 *
 * sse_starlette emits frames as:
 *   event: <name>\n
 *   data: <payload>\n
 *   \n
 *
 * We split the buffer on "\n\n" per frame and read `event:` + `data:` lines.
 * Unknown event names (e.g. sse_starlette's keepalives) are ignored.
 */
export async function streamChat(
  req: ChatRequest,
  domain: string,
  handlers: StreamHandlers,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Domain': domain,
        Accept: 'text/event-stream',
      },
      body: JSON.stringify(req),
    });
  } catch (err) {
    handlers.onError(err instanceof Error ? err.message : 'network error');
    return;
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = String(body.detail);
    } catch {
      /* empty */
    }
    handlers.onError(detail);
    return;
  }

  if (!res.body) {
    handlers.onError('empty response body');
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  // sse_starlette emits frames terminated by CRLF CRLF, but the SSE spec also
  // allows LF LF. Normalize CRLF → LF up front so the frame split is a single
  // string search on "\n\n".
  const findFrameEnd = (buf: string): number => buf.indexOf('\n\n');

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    // Normalize line endings inside the sliding buffer.
    buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n');

    let idx: number;
    while ((idx = findFrameEnd(buffer)) !== -1) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const lines = frame.split('\n');
      let eventName = 'message';
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
      }
      const data = dataLines.join('\n');
      if (eventName === 'token') handlers.onToken(data);
      else if (eventName === 'done') {
        handlers.onDone();
        return;
      } else if (eventName === 'error') {
        handlers.onError(data);
        return;
      }
    }
  }

  handlers.onDone();
}
