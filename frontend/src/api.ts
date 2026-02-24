const RAW_API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
// Normalize to avoid double slashes when building URLs
const API_BASE = RAW_API_BASE.replace(/\/+$/, "");

export interface Person {
  email: string;
  name: string;
  cluster?: number;
  cluster_name?: string;
  degree?: number;
}

export interface Edge {
  source: string;
  target: string;
  properties: {
    summary?: string;
    email_count?: number;
    comments?: string[];
    [key: string]: unknown;
  };
}

export interface GraphData {
  nodes: Person[];
  edges: Edge[];
}

export interface MetaCounts {
  node_count: number;
  edge_count: number;
}

export interface Degree {
  email: string;
  name: string;
  degree: number;
}

export interface MetaData {
  counts: MetaCounts;
  degrees: Degree[];
}

export interface RagSource {
  namespace?: string;
  score?: number;
  type?: string;
  text_preview?: string;
}

export interface RagQueryResult {
  answer: string;
  sources: RagSource[];
  model: string;
}

export async function queryRag(
  question: string,
  options?: { model?: string; namespaces?: string[] }
): Promise<RagQueryResult> {
  const res = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      model: options?.model ?? undefined,
      namespaces: options?.namespaces ?? undefined,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err.detail as string) || "RAG query failed");
  }
  return res.json();
}

export async function fetchGraph(recluster = false): Promise<GraphData> {
  const url = recluster ? `${API_BASE}/graph?recluster=1` : `${API_BASE}/graph`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err.detail as string) || `Failed to fetch graph (status ${res.status})`);
  }
  return res.json();
}

export async function fetchSubgraph(email: string, depth = 1): Promise<GraphData> {
  const res = await fetch(`${API_BASE}/graph/${encodeURIComponent(email)}?depth=${depth}`);
  if (!res.ok) throw new Error("Person not found");
  return res.json();
}

export async function fetchMeta(): Promise<MetaData> {
  const res = await fetch(`${API_BASE}/meta`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err.detail as string) || `Failed to fetch meta (status ${res.status})`);
  }
  return res.json();
}

export async function summarizeEdge(source: string, target: string): Promise<{ summary: string }> {
  const res = await fetch(`${API_BASE}/graph/summarize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source, target }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Summarization failed");
  }
  return res.json();
}

export interface Insight {
  type: "node_anomaly" | "bridge_edge" | "high_centrality";
  title: string;
  description: string;
  severity: number;
  nodes: string[];
  edges: { source: string; target: string }[];
}

export async function fetchInsights(): Promise<{ insights: Insight[] }> {
  const res = await fetch(`${API_BASE}/insights`);
  if (!res.ok) throw new Error("Failed to fetch insights");
  return res.json();
}
