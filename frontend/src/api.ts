const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface Person {
  email: string;
  name: string;
  cluster?: number;
  cluster_name?: string;
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

export async function fetchGraph(recluster = false): Promise<GraphData> {
  const url = recluster ? `${API_BASE}/graph?recluster=1` : `${API_BASE}/graph`;
  const res = await fetch(url);
  return res.json();
}

export async function fetchSubgraph(email: string, depth = 1): Promise<GraphData> {
  const res = await fetch(`${API_BASE}/graph/${encodeURIComponent(email)}?depth=${depth}`);
  if (!res.ok) throw new Error("Person not found");
  return res.json();
}

export async function fetchMeta(): Promise<MetaData> {
  const res = await fetch(`${API_BASE}/meta`);
  return res.json();
}
