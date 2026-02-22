import { useEffect, useState, useMemo } from "react";
import GraphView from "./GraphView";
import { fetchGraph, fetchSubgraph, fetchMeta, type GraphData, type MetaData, type Edge } from "./api";

const CLUSTER_COLORS = ["#6366f1","#f97316","#22c55e","#ec4899","#06b6d4","#eab308","#a855f7","#ef4444","#14b8a6","#f59e0b"];

const CLUSTER_LABELS: Record<number, string> = {
  0: "Securities Fraud",
  1: "Money Laundering",
  2: "Identity Theft",
  3: "Wire Fraud / Phishing",
  4: "Insider Trading",
};

type ViewMode = "graph" | "clusters";

function toGraphNodes(data: GraphData) {
  return data.nodes.map((n) => ({ id: n.email, name: n.name, cluster: n.cluster ?? 0, isClusterNode: false }));
}

function toGraphLinks(data: GraphData) {
  return data.edges.map((e) => ({
    source: e.source,
    target: e.target,
    count: (e.properties?.email_count as number) ?? 1,
    summary: (e.properties?.summary as string) ?? "",
  }));
}

/**
 * Build collapsed cluster view: one super-node per cluster,
 * with inter-cluster edges aggregated.
 */
function toClusterGraph(data: GraphData) {
  // Group nodes by cluster
  const clusterMap = new Map<number, typeof data.nodes>();
  data.nodes.forEach((n) => {
    const c = n.cluster ?? 0;
    if (!clusterMap.has(c)) clusterMap.set(c, []);
    clusterMap.get(c)!.push(n);
  });

  // Build email-to-cluster lookup
  const emailToCluster = new Map<string, number>();
  data.nodes.forEach((n) => emailToCluster.set(n.email, n.cluster ?? 0));

  // Create super-nodes
  const nodes = [...clusterMap.entries()].map(([id, members]) => ({
    id: `cluster-${id}`,
    name: `${CLUSTER_LABELS[id] ?? `Cluster ${id}`} (${members.length})`,
    cluster: id,
    isClusterNode: true,
    memberCount: members.length,
  }));

  // Aggregate inter-cluster edges
  const edgeKey = (a: number, b: number) => `${Math.min(a, b)}-${Math.max(a, b)}`;
  const aggregated = new Map<string, { source: number; target: number; count: number }>();

  data.edges.forEach((e) => {
    const cSrc = emailToCluster.get(e.source);
    const cTgt = emailToCluster.get(e.target);
    if (cSrc == null || cTgt == null || cSrc === cTgt) return;
    const key = edgeKey(cSrc, cTgt);
    if (!aggregated.has(key)) {
      aggregated.set(key, { source: Math.min(cSrc, cTgt), target: Math.max(cSrc, cTgt), count: 0 });
    }
    aggregated.get(key)!.count += (e.properties?.email_count as number) ?? 1;
  });

  const links = [...aggregated.values()].map((e) => ({
    source: `cluster-${e.source}`,
    target: `cluster-${e.target}`,
    count: e.count,
    summary: "",
  }));

  return { nodes, links };
}

export default function App() {
  const [fullGraphData, setFullGraphData] = useState<GraphData | null>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [meta, setMeta] = useState<MetaData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("graph");
  const [expandedCluster, setExpandedCluster] = useState<number | null>(null);

  useEffect(() => {
    fetchGraph().then((data) => {
      setFullGraphData(data);
      setGraphData(data);
    }).catch(() => setError("Could not connect to API. Is the backend running?"));
    fetchMeta().then(setMeta).catch(() => {});
  }, []);

  // Compute the displayed nodes/links based on view mode
  const displayData = useMemo(() => {
    if (!graphData) return null;

    if (viewMode === "graph") {
      return { nodes: toGraphNodes(graphData), links: toGraphLinks(graphData) };
    }

    // Cluster mode
    if (expandedCluster != null) {
      // Show only nodes in the expanded cluster + their internal edges
      const clusterNodes = graphData.nodes.filter((n) => (n.cluster ?? 0) === expandedCluster);
      const clusterEmails = new Set(clusterNodes.map((n) => n.email));
      const clusterEdges = graphData.edges.filter(
        (e) => clusterEmails.has(e.source) && clusterEmails.has(e.target)
      );
      const subData: GraphData = { nodes: clusterNodes, edges: clusterEdges };
      return { nodes: toGraphNodes(subData), links: toGraphLinks(subData) };
    }

    // Collapsed cluster view
    const { nodes, links } = toClusterGraph(graphData);
    return { nodes, links };
  }, [graphData, viewMode, expandedCluster]);

  const handleNodeClick = async (id: string) => {
    if (viewMode === "clusters" && id.startsWith("cluster-")) {
      const clusterId = parseInt(id.replace("cluster-", ""), 10);
      setExpandedCluster(clusterId);
      setSelected(null);
      setSelectedEdge(null);
      return;
    }

    setSelected(id);
    setSelectedEdge(null);

    if (viewMode === "graph") {
      try {
        const sub = await fetchSubgraph(id, 2);
        setGraphData(sub);
      } catch {
        setError("Failed to load subgraph");
      }
    }
  };

  const handleLinkClick = (source: string, target: string) => {
    if (!graphData) return;
    const edge = graphData.edges.find(
      (e) =>
        (e.source === source && e.target === target) ||
        (e.source === target && e.target === source)
    );
    if (edge) setSelectedEdge(edge);
  };

  const handleReset = async () => {
    setSelected(null);
    setSelectedEdge(null);
    setExpandedCluster(null);
    try {
      const full = fullGraphData ?? await fetchGraph();
      setGraphData(full);
      setFullGraphData(full);
    } catch {
      setError("Failed to reload graph");
    }
  };

  const handleViewModeChange = (mode: ViewMode) => {
    setViewMode(mode);
    setSelected(null);
    setSelectedEdge(null);
    setExpandedCluster(null);
    if (fullGraphData) setGraphData(fullGraphData);
  };

  const sourceName = graphData?.nodes.find(n => n.email === selectedEdge?.source)?.name ?? selectedEdge?.source;
  const targetName = graphData?.nodes.find(n => n.email === selectedEdge?.target)?.name ?? selectedEdge?.target;

  // Build cluster info for legend
  const clusterInfo = useMemo(() => {
    if (!graphData) return [];
    const clusters = new Map<number, string[]>();
    graphData.nodes.forEach(n => {
      const c = n.cluster ?? 0;
      if (!clusters.has(c)) clusters.set(c, []);
      clusters.get(c)!.push(n.name);
    });
    return [...clusters.entries()].sort((a, b) => a[0] - b[0]);
  }, [graphData]);

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0f172a", color: "#e2e8f0", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* Sidebar */}
      <aside style={{ width: 280, padding: 20, borderRight: "1px solid #1e293b", overflowY: "auto", flexShrink: 0 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>ProjectNexus</h1>

        {/* View mode toggle */}
        <div style={{ marginBottom: 16, display: "flex", gap: 4, background: "#1e293b", borderRadius: 8, padding: 4 }}>
          <button
            onClick={() => handleViewModeChange("graph")}
            style={{
              flex: 1, padding: "6px 0", fontSize: 12, fontWeight: 600, border: "none", borderRadius: 6, cursor: "pointer",
              background: viewMode === "graph" ? "#6366f1" : "transparent",
              color: viewMode === "graph" ? "#fff" : "#94a3b8",
            }}
          >
            Graph
          </button>
          <button
            onClick={() => handleViewModeChange("clusters")}
            style={{
              flex: 1, padding: "6px 0", fontSize: 12, fontWeight: 600, border: "none", borderRadius: 6, cursor: "pointer",
              background: viewMode === "clusters" ? "#6366f1" : "transparent",
              color: viewMode === "clusters" ? "#fff" : "#94a3b8",
            }}
          >
            Clusters
          </button>
        </div>

        {meta && (
          <div style={{ marginBottom: 20, fontSize: 13, color: "#94a3b8" }}>
            <p>{meta.counts.node_count} people &middot; {meta.counts.edge_count} connections</p>
          </div>
        )}

        {/* Expanded cluster info */}
        {viewMode === "clusters" && expandedCluster != null && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: "#94a3b8" }}>Viewing cluster:</p>
            <p style={{ fontWeight: 600, color: CLUSTER_COLORS[expandedCluster % CLUSTER_COLORS.length] }}>
              {CLUSTER_LABELS[expandedCluster] ?? `Cluster ${expandedCluster}`}
            </p>
            <button
              onClick={() => setExpandedCluster(null)}
              style={{ marginTop: 8, padding: "6px 12px", fontSize: 13, background: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, cursor: "pointer" }}
            >
              ← Back to clusters
            </button>
          </div>
        )}

        {selected && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: "#94a3b8" }}>Focused on:</p>
            <p style={{ fontWeight: 600, color: "#f97316" }}>{selected}</p>
            <button
              onClick={handleReset}
              style={{ marginTop: 8, padding: "6px 12px", fontSize: 13, background: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, cursor: "pointer" }}
            >
              Show full graph
            </button>
          </div>
        )}

        {/* Relationship detail panel */}
        {selectedEdge && (
          <div style={{ marginBottom: 16, padding: 12, background: "#1e293b", borderRadius: 8, border: "1px solid #334155" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
              <h3 style={{ fontSize: 13, fontWeight: 600, color: "#38bdf8" }}>Relationship</h3>
              <button
                onClick={() => setSelectedEdge(null)}
                style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 16, padding: 0 }}
              >
                ✕
              </button>
            </div>
            <p style={{ fontSize: 13, color: "#f97316", fontWeight: 600, marginBottom: 4 }}>
              {sourceName}
            </p>
            <p style={{ fontSize: 11, color: "#64748b", marginBottom: 4, textAlign: "center" }}>↕</p>
            <p style={{ fontSize: 13, color: "#f97316", fontWeight: 600, marginBottom: 8 }}>
              {targetName}
            </p>
            {selectedEdge.properties.email_count != null && (
              <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                📧 <strong>{selectedEdge.properties.email_count}</strong> emails exchanged
              </p>
            )}
            {selectedEdge.properties.summary && (
              <p style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.5 }}>
                {selectedEdge.properties.summary}
              </p>
            )}
          </div>
        )}

        {/* Cluster legend */}
        {clusterInfo.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>Clusters</h3>
            {clusterInfo.map(([id, names]) => (
              <div
                key={id}
                onClick={() => { if (viewMode === "clusters") setExpandedCluster(id); }}
                style={{ marginBottom: 6, fontSize: 12, cursor: viewMode === "clusters" ? "pointer" : "default" }}
              >
                <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: CLUSTER_COLORS[id % CLUSTER_COLORS.length], marginRight: 6, verticalAlign: "middle" }} />
                <span style={{ color: expandedCluster === id ? CLUSTER_COLORS[id % CLUSTER_COLORS.length] : "#cbd5e1" }}>
                  {CLUSTER_LABELS[id] ?? `Cluster ${id}`}
                </span>
                <span style={{ color: "#64748b" }}> ({names.length})</span>
              </div>
            ))}
          </div>
        )}

        {meta && (
          <div>
            <h3 style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: "#94a3b8" }}>By degree</h3>
            <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 13 }}>
              {meta.degrees.map((d) => (
                <li
                  key={d.email}
                  onClick={() => handleNodeClick(d.email)}
                  style={{ padding: "4px 0", cursor: "pointer", color: d.email === selected ? "#f97316" : "#cbd5e1" }}
                >
                  {d.name} <span style={{ color: "#64748b" }}>({d.degree})</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </aside>

      {/* Graph */}
      <main style={{ flex: 1, position: "relative" }}>
        {error && (
          <div style={{ position: "absolute", top: 20, left: 20, padding: "10px 16px", background: "#7f1d1d", borderRadius: 8, fontSize: 14, zIndex: 10 }}>
            {error}
          </div>
        )}
        {displayData ? (
          <GraphView
            nodes={displayData.nodes}
            links={displayData.links}
            selectedNode={selected}
            onNodeClick={handleNodeClick}
            onLinkClick={handleLinkClick}
            width={window.innerWidth - 280}
            height={window.innerHeight}
            showClusters={viewMode === "clusters"}
          />
        ) : (
          !error && <p style={{ padding: 40 }}>Loading graph...</p>
        )}
      </main>
    </div>
  );
}
