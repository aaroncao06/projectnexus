import { useEffect, useState, useMemo } from "react";
import GraphView from "./GraphView";
import { fetchGraph, fetchMeta, summarizeEdge, type GraphData, type MetaData, type Edge } from "./api";

const CLUSTER_COLORS = ["#6366f1", "#f97316", "#22c55e", "#ec4899", "#06b6d4", "#eab308", "#a855f7", "#ef4444", "#14b8a6", "#f59e0b"];

type ViewMode = "graph" | "clusters";

/** Derive cluster id -> display name from nodes (uses cluster_name from API when set). */
function getClusterNameMap(nodes: { cluster?: number; cluster_name?: string }[]): Map<number, string> {
  const map = new Map<number, string>();
  nodes.forEach((n) => {
    const c = n.cluster ?? 0;
    if (!map.has(c)) map.set(c, n.cluster_name ?? `Cluster ${c}`);
  });
  return map;
}

function toGraphNodes(data: GraphData) {
  return data.nodes.map((n) => ({ id: n.email, name: n.name, cluster: n.cluster ?? 0, isClusterNode: false, degree: n.degree ?? 0 }));
}

function toGraphLinks(data: GraphData) {
  const map = new Map<string, any>();
  data.edges.forEach((e) => {
    const key = [e.source, e.target].sort().join("<->");
    const count = (e.properties?.email_count as number) ?? 1;
    if (map.has(key)) {
      map.get(key).count += count;
      if (e.properties?.summary && !map.get(key).summary.includes(e.properties.summary)) {
        map.get(key).summary += " | " + e.properties.summary;
      }
    } else {
      map.set(key, {
        source: e.source,
        target: e.target,
        count,
        summary: (e.properties?.summary as string) ?? "",
      });
    }
  });
  return Array.from(map.values());
}

/**
 * Build collapsed cluster view: one super-node per cluster,
 * with inter-cluster edges aggregated.
 */
function toClusterGraph(data: GraphData) {
  const clusterNameMap = getClusterNameMap(data.nodes);

  const clusterMap = new Map<number, typeof data.nodes>();
  data.nodes.forEach((n) => {
    const c = n.cluster ?? 0;
    if (!clusterMap.has(c)) clusterMap.set(c, []);
    clusterMap.get(c)!.push(n);
  });

  const emailToCluster = new Map<string, number>();
  data.nodes.forEach((n) => emailToCluster.set(n.email, n.cluster ?? 0));

  const nodes = [...clusterMap.entries()].map(([id, members]) => ({
    id: `cluster-${id}`,
    name: `${clusterNameMap.get(id) ?? `Cluster ${id}`} (${members.length})`,
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
  const [selectedNodes, setSelectedNodes] = useState<Set<string>>(new Set());
  const [lastSelected, setLastSelected] = useState<string | null>(null);
  const [selectedEdge, setSelectedEdge] = useState<Edge | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("graph");
  const [expandedCluster, setExpandedCluster] = useState<number | null>(null);
  const [reclustering, setReclustering] = useState(false);
  const [layoutSignal, setLayoutSignal] = useState(0);
  const [boxSelectMode, setBoxSelectMode] = useState(false);
  const [showComments, setShowComments] = useState(false);
  const [isSummarizingEdge, setIsSummarizingEdge] = useState(false);
  const [showClustersList, setShowClustersList] = useState(false);
  const [showDegreesList, setShowDegreesList] = useState(false);
  const [showConnectionsList, setShowConnectionsList] = useState(false);
  const [subgraphDepth, setSubgraphDepth] = useState(1);
  const [hiddenNodes, setHiddenNodes] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [connectionsSearch, setConnectionsSearch] = useState("");
  const [connectionsSearchQuery, setConnectionsSearchQuery] = useState("");
  const [minDegree, setMinDegree] = useState(1);

  const handleSummarizeEdge = async () => {
    if (!selectedEdge) return;
    setIsSummarizingEdge(true);
    try {
      const { summary } = await summarizeEdge(selectedEdge.source, selectedEdge.target);
      // Update local state to show the new summary immediately
      if (graphData) {
        const nextEdges = graphData.edges.map(e => {
          if ((e.source === selectedEdge.source && e.target === selectedEdge.target) ||
            (e.source === selectedEdge.target && e.target === selectedEdge.source)) {
            return { ...e, properties: { ...e.properties, summary } };
          }
          return e;
        });
        const nextData = { ...graphData, edges: nextEdges };
        setGraphData(nextData);
        if (fullGraphData) setFullGraphData(nextData);
        setSelectedEdge({ ...selectedEdge, properties: { ...selectedEdge.properties, summary } });
      }
    } catch (e: any) {
      setError(e.message || "Failed to summarize relationship");
    } finally {
      setIsSummarizingEdge(false);
    }
  };

  useEffect(() => {
    fetchGraph().then((data) => {
      setFullGraphData(data);
      setGraphData(data);
    }).catch(() => setError("Could not connect to API. Is the backend running?"));
    fetchMeta().then(setMeta).catch(() => { });
  }, []);

  // Handle global escape key to return to full graph
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        handleReset();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [fullGraphData]); // Only depends on fullGraphData which is stable

  const maxSubgraphDepth = useMemo(() => {
    if (!lastSelected || !fullGraphData) return 3;
    const distances = new Map<string, number>();
    distances.set(lastSelected, 0);
    const queue = [lastSelected];
    let maxD = 0;
    const adj = new Map<string, string[]>();
    fullGraphData.edges.forEach(e => {
      if (!adj.has(e.source)) adj.set(e.source, []);
      if (!adj.has(e.target)) adj.set(e.target, []);
      adj.get(e.source)!.push(e.target);
      adj.get(e.target)!.push(e.source);
    });
    while (queue.length > 0) {
      const u = queue.shift()!;
      const d = distances.get(u)!;
      maxD = Math.max(maxD, d);
      (adj.get(u) || []).forEach(v => {
        if (!distances.has(v)) {
          distances.set(v, d + 1);
          queue.push(v);
        }
      });
    }
    return Math.max(1, maxD);
  }, [lastSelected, fullGraphData]);

  const neighbors = useMemo(() => {
    if (!lastSelected || !fullGraphData) return [];
    const direct = new Set<string>();
    fullGraphData.edges.forEach(e => {
      if (e.source === lastSelected) direct.add(e.target);
      if (e.target === lastSelected) direct.add(e.source);
    });
    return Array.from(direct).map(email => ({
      email,
      name: fullGraphData.nodes.find(n => n.email === email)?.name || email
    })).sort((a, b) => (a.name || a.email).localeCompare(b.name || b.email));
  }, [lastSelected, fullGraphData]);

  // Compute the displayed nodes/links based on view mode
  const displayData = useMemo(() => {
    if (!graphData) return null;

    // Filter raw graph data first
    const visibleNodes = graphData.nodes.filter(n => !hiddenNodes.has(n.email) && (n.degree ?? 0) >= minDegree);
    const visibleEmails = new Set(visibleNodes.map(n => n.email));
    const visibleEdges = graphData.edges.filter(e => visibleEmails.has(e.source) && visibleEmails.has(e.target));
    const filteredGraphData: GraphData = { nodes: visibleNodes, edges: visibleEdges };

    const finalize = (data: { nodes: any[], links: any[] }) => {
      // Sort nodes only by degree so hubs show on top.
      // We do NOT sort by selection here anymore, to keep the array reference stable
      // when users click around, preventing simulation resets.
      data.nodes.sort((a, b) => {
        const aDeg = a.degree || 0;
        const bDeg = b.degree || 0;
        return aDeg - bDeg;
      });
      return data;
    };

    if (viewMode === "graph") {
      return finalize({ nodes: toGraphNodes(filteredGraphData), links: toGraphLinks(filteredGraphData) });
    }

    // Cluster mode
    if (expandedCluster != null) {
      // Show only nodes in the expanded cluster + their internal edges (already filtered by visibility)
      const clusterNodes = filteredGraphData.nodes.filter((n) => (n.cluster ?? 0) === expandedCluster);
      const clusterEmails = new Set(clusterNodes.map((n) => n.email));
      const clusterEdges = filteredGraphData.edges.filter(
        (e) => clusterEmails.has(e.source) && clusterEmails.has(e.target)
      );
      const subData: GraphData = { nodes: clusterNodes, edges: clusterEdges };
      return finalize({ nodes: toGraphNodes(subData), links: toGraphLinks(subData) });
    }

    // Collapsed cluster view
    const { nodes, links } = toClusterGraph(filteredGraphData);
    return { nodes, links };
  }, [graphData, viewMode, expandedCluster, hiddenNodes, minDegree]);

  const handleToggleVisibility = (email: string) => {
    setHiddenNodes(prev => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
    setLayoutSignal(s => s + 1);
  };

  const handleHideSelected = () => {
    setHiddenNodes(prev => {
      const next = new Set(prev);
      selectedNodes.forEach(email => next.add(email));
      return next;
    });
    setLayoutSignal(s => s + 1);
  };

  const handleShowSelected = () => {
    setHiddenNodes(prev => {
      const next = new Set(prev);
      selectedNodes.forEach(email => next.delete(email));
      return next;
    });
    setLayoutSignal(s => s + 1);
  };

  const handleShowOnly = () => {
    if (!fullGraphData) return;
    const allEmails = fullGraphData.nodes.map(n => n.email);
    const nextHidden = new Set<string>();
    allEmails.forEach(email => {
      if (!selectedNodes.has(email)) nextHidden.add(email);
    });
    setHiddenNodes(nextHidden);
    setLayoutSignal(s => s + 1);
  };

  const handleShowEverything = () => {
    setHiddenNodes(new Set());
    setLayoutSignal(s => s + 1);
  };

  const handleHideEverything = () => {
    if (!fullGraphData) return;
    setHiddenNodes(new Set(fullGraphData.nodes.map(n => n.email)));
    setLayoutSignal(s => s + 1);
  };

  const handleNodeClick = async (id: string, isShift: boolean) => {
    if (viewMode === "clusters" && id.startsWith("cluster-")) {
      const clusterId = parseInt(id.replace("cluster-", ""), 10);
      setExpandedCluster(clusterId);
      setSelectedNodes(new Set());
      setLastSelected(null);
      setSelectedEdge(null);
      return;
    }

    if (isShift) {
      setSelectedNodes(prev => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        return next;
      });
    } else {
      setSelectedNodes(new Set([id]));
    }
    setLastSelected(id);
    setSelectedEdge(null);
  };

  const handleLoadSubgraph = () => {
    if (!lastSelected || !fullGraphData) return;

    // Calculate local neighborhood within fullGraphData
    const neighbors = new Set<string>([lastSelected]);
    let currentLevel = new Set<string>([lastSelected]);

    for (let i = 0; i < subgraphDepth; i++) {
      const nextLevel = new Set<string>();
      fullGraphData.edges.forEach(e => {
        if (currentLevel.has(e.source)) nextLevel.add(e.target);
        if (currentLevel.has(e.target)) nextLevel.add(e.source);
      });
      nextLevel.forEach(nodeId => neighbors.add(nodeId));
      currentLevel = nextLevel;
    }

    // Hide everything NOT in the neighborhood
    const nextHidden = new Set<string>();
    fullGraphData.nodes.forEach(n => {
      if (!neighbors.has(n.email)) nextHidden.add(n.email);
    });

    setHiddenNodes(nextHidden);
    setSelectedNodes(new Set([lastSelected]));
    setLayoutSignal(s => s + 1);
  };

  const handleClusterClick = (clusterId: number) => {
    if (!graphData) return;
    const clusterNodes = graphData.nodes.filter(n => n.cluster === clusterId);
    const nodeIds = clusterNodes.map(n => n.email);
    setSelectedNodes(new Set(nodeIds));
    if (nodeIds.length > 0) setLastSelected(nodeIds[nodeIds.length - 1]);
    setSelectedEdge(null);
    if (viewMode === "clusters") {
      setExpandedCluster(clusterId);
    }
  };


  const handleNodesSelect = (ids: string[]) => {
    setSelectedNodes(new Set(ids));
    if (ids.length > 0) setLastSelected(ids[ids.length - 1]);
    setSelectedEdge(null);
  };

  const handleBackgroundClick = () => {
    setSelectedNodes(new Set());
    setLastSelected(null);
    setSelectedEdge(null);
  };

  const handleLinkClick = (source: string, target: string) => {
    if (!graphData) return;
    const edge = graphData.edges.find(
      (e) =>
        (e.source === source && e.target === target) ||
        (e.source === target && e.target === source)
    );
    if (edge) {
      setSelectedNodes(new Set([source, target]));
      setLastSelected(source);
      setSelectedEdge(edge);
      setShowComments(false);
    }
  };

  const handleReset = () => {
    setSelectedNodes(new Set());
    setHiddenNodes(new Set());
    setLastSelected(null);
    setSelectedEdge(null);
    setExpandedCluster(null);
    setShowComments(false);
    setMinDegree(1);
    setLayoutSignal(s => s + 1);
  };

  const handleRecluster = async () => {
    setReclustering(true);
    setError(null);
    try {
      const full = await fetchGraph(true);
      setFullGraphData(full);
      setGraphData(full);
      setSelectedNodes(new Set());
      setLastSelected(null);
      setSelectedEdge(null);
      setExpandedCluster(null);
    } catch {
      setError("Recluster failed. Is OPENROUTER_API_KEY set on the backend?");
    } finally {
      setReclustering(false);
    }
  };

  const handleViewModeChange = (mode: ViewMode) => {
    setViewMode(mode);
    setSelectedNodes(new Set());
    setLastSelected(null);
    setSelectedEdge(null);
    setExpandedCluster(null);
    setBoxSelectMode(false);
    if (fullGraphData) setGraphData(fullGraphData);
  };

  const clusterNameMap = useMemo(() => graphData ? getClusterNameMap(graphData.nodes) : new Map<number, string>(), [graphData]);

  const clusterInfo = useMemo(() => {
    if (!graphData) return [];
    const clusters = new Map<number, string[]>();
    graphData.nodes.forEach(n => {
      const c = n.cluster ?? 0;
      if (!clusters.has(c)) clusters.set(c, []);
      clusters.get(c)!.push(n.name);
    });
    return [...clusters.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [graphData]);

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0f172a", color: "#e2e8f0", fontFamily: "Inter, system-ui, sans-serif" }}>
      {/* Sidebar */}
      <aside style={{ width: 320, padding: 20, borderRight: "1px solid #1e293b", overflowY: "auto", flexShrink: 0 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, marginBottom: 16 }}>ProjectNexus</h1>

        {meta && (
          <div style={{ marginBottom: 20, fontSize: 13, color: "#94a3b8" }}>
            <p>{meta.counts.node_count} people &middot; {meta.counts.edge_count} connections</p>
            <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
              <button
                onClick={() => setLayoutSignal((s) => s + 1)}
                style={{
                  flex: 1,
                  padding: "8px 12px",
                  fontSize: 13,
                  fontWeight: 600,
                  background: "#334155",
                  color: "#e2e8f0",
                  border: "1px solid #475569",
                  borderRadius: 6,
                  cursor: "pointer",
                }}
              >
                Respace
              </button>
              <button
                onClick={() => setBoxSelectMode(!boxSelectMode)}
                style={{
                  flex: 1,
                  padding: "8px 12px",
                  fontSize: 13,
                  fontWeight: 600,
                  background: boxSelectMode ? "#6366f1" : "#334155",
                  color: boxSelectMode ? "#fff" : "#e2e8f0",
                  border: `1px solid ${boxSelectMode ? "#6366f1" : "#475569"}`,
                  borderRadius: 6,
                  cursor: "pointer",
                }}
              >
                {boxSelectMode ? "Select: ON" : "Select"}
              </button>
            </div>
          </div>
        )}

        {/* Expanded cluster info */}
        {viewMode === "clusters" && expandedCluster != null && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: "#94a3b8" }}>Viewing cluster:</p>
            <p style={{ fontWeight: 600, color: CLUSTER_COLORS[expandedCluster % CLUSTER_COLORS.length] }}>
              {clusterNameMap.get(expandedCluster) ?? `Cluster ${expandedCluster}`}
            </p>
            <button
              onClick={() => setExpandedCluster(null)}
              style={{ marginTop: 8, padding: "6px 12px", fontSize: 13, background: "#1e293b", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 6, cursor: "pointer" }}
            >
              ← Back to clusters
            </button>
          </div>
        )}

        {lastSelected && selectedNodes.size === 1 && (
          <div style={{ marginBottom: 16 }}>
            {lastSelected && (
              <>
                <p style={{ fontSize: 13, color: "#94a3b8" }}>Focused on:</p>
                <p style={{ fontWeight: 600, color: "#f97316" }}>{lastSelected}</p>
                {viewMode === "graph" && (
                  <div style={{ marginTop: 8, display: "flex", gap: 4 }}>
                    <button
                      onClick={handleLoadSubgraph}
                      style={{ flex: 1, padding: "6px 12px", fontSize: 13, background: "#334155", color: "#e2e8f0", border: "1px solid #475569", borderRadius: 6, cursor: "pointer" }}
                    >
                      View connections
                    </button>
                    <select
                      value={subgraphDepth > maxSubgraphDepth ? 1 : subgraphDepth}
                      onChange={(e) => setSubgraphDepth(parseInt(e.target.value))}
                      style={{ padding: "6px 4px", fontSize: 13, background: "#1e293b", color: "#e2e8f0", border: "1px solid #475569", borderRadius: 6, cursor: "pointer" }}
                      title="Connection depth"
                    >
                      {Array.from({ length: Math.min(10, maxSubgraphDepth) }, (_, i) => i + 1).map(d => (
                        <option key={d} value={d}>{d}º</option>
                      ))}
                    </select>
                  </div>
                )}
                {selectedNodes.size > 0 && (
                  <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 6 }}>
                    <button
                      onClick={handleHideSelected}
                      style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
                    >
                      Hide selected
                    </button>
                    <button
                      onClick={handleShowSelected}
                      style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
                    >
                      Show selected
                    </button>
                    <button
                      onClick={handleShowOnly}
                      style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
                    >
                      Show only
                    </button>
                  </div>
                )}

                {/* Neighbors List */}
                {neighbors.length > 0 && (
                  <div style={{ marginTop: 16 }}>
                    <button
                      onClick={() => setShowConnectionsList(!showConnectionsList)}
                      style={{
                        width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
                        background: "none", border: "none", padding: 0, marginBottom: 8, cursor: "pointer",
                        textAlign: "left"
                      }}
                    >
                      <span style={{ fontSize: 12, fontWeight: 600, color: "#94a3b8", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                        Direct Connections ({neighbors.length})
                      </span>
                      <span style={{ fontSize: 10, color: "#64748b" }}>{showConnectionsList ? "▼" : "▶"}</span>
                    </button>
                    {showConnectionsList && <>
                      <div style={{ marginBottom: 8 }}>
                        <input
                          type="text"
                          placeholder="Search connections (Enter)..."
                          value={connectionsSearch}
                          onChange={(e) => setConnectionsSearch(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              setConnectionsSearchQuery(connectionsSearch);
                            }
                          }}
                          style={{
                            width: "100%",
                            padding: "6px 10px",
                            fontSize: 12,
                            background: "#1e293b",
                            border: "1px solid #334155",
                            borderRadius: 6,
                            color: "#f8fafc",
                            outline: "none",
                          }}
                        />
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {neighbors
                          .filter(n => {
                            if (!connectionsSearchQuery) return true;
                            const q = connectionsSearchQuery.toLowerCase();
                            return (n.name?.toLowerCase().includes(q) || n.email.toLowerCase().includes(q));
                          })
                          .map(n => {
                            const isExpanded = selectedEdge && (
                              (selectedEdge.source === lastSelected && selectedEdge.target === n.email) ||
                              (selectedEdge.target === lastSelected && selectedEdge.source === n.email)
                            );
                            return (
                              <div key={n.email} style={{ borderBottom: "1px solid #1e293b" }}>
                                <button
                                  onClick={() => {
                                    if (isExpanded) {
                                      setSelectedEdge(null);
                                    } else {
                                      // Find and show the edge details without changing node selection
                                      const edge = graphData?.edges.find(
                                        (e) =>
                                          (e.source === lastSelected && e.target === n.email) ||
                                          (e.source === n.email && e.target === lastSelected)
                                      );
                                      if (edge) {
                                        setSelectedEdge(edge);
                                        setShowComments(false);
                                      }
                                    }
                                  }}
                                  style={{
                                    width: "100%", padding: "6px 0", textAlign: "left", background: "none", border: "none",
                                    cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center"
                                  }}
                                >
                                  <span style={{ fontSize: 13, color: isExpanded ? "#38bdf8" : "#cbd5e1", fontWeight: isExpanded ? 600 : 400 }}>
                                    {n.name || n.email}
                                  </span>
                                  <span style={{ fontSize: 10, color: "#64748b" }}>{isExpanded ? "▼" : "▶"}</span>
                                </button>
                                {isExpanded && selectedEdge && (
                                  <div style={{ padding: "8px 0 12px 12px", borderLeft: "2px solid #38bdf8", marginBottom: 8 }}>
                                    {selectedEdge.properties.email_count != null && (
                                      <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                                        📧 <strong>{selectedEdge.properties.email_count}</strong> emails exchanged
                                      </p>
                                    )}
                                    {selectedEdge.properties.summary ? (
                                      <p style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.5, marginBottom: 10 }}>
                                        {selectedEdge.properties.summary}
                                      </p>
                                    ) : (
                                      <button
                                        onClick={handleSummarizeEdge}
                                        disabled={isSummarizingEdge}
                                        style={{
                                          width: "100%", padding: "8px", fontSize: 12,
                                          background: "#334155", color: "#e2e8f0",
                                          border: "1px solid #475569", borderRadius: 6,
                                          cursor: isSummarizingEdge ? "wait" : "pointer",
                                          marginBottom: 10
                                        }}
                                      >
                                        {isSummarizingEdge ? "Generating..." : "Generate Summary"}
                                      </button>
                                    )}

                                    {selectedEdge.properties.comments && (selectedEdge.properties.comments as string[]).length > 0 && (
                                      <div style={{ marginTop: 8 }}>
                                        <button
                                          onClick={() => setShowComments(!showComments)}
                                          style={{
                                            display: "flex", alignItems: "center", gap: 6,
                                            background: "none", border: "none", color: "#6366f1",
                                            fontSize: 11, fontWeight: 600, cursor: "pointer", padding: 0,
                                            marginBottom: 6
                                          }}
                                        >
                                          {showComments ? "▼ Hide observations" : "▶ Show raw observations"}
                                          <span style={{ fontSize: 10, color: "#64748b" }}>({(selectedEdge.properties.comments as string[]).length})</span>
                                        </button>
                                        {showComments && (
                                          <ul style={{
                                            margin: 0, paddingLeft: 16, fontSize: 11, color: "#94a3b8",
                                            display: "flex", flexDirection: "column", gap: 6,
                                            maxHeight: 200, overflowY: "auto"
                                          }}>
                                            {(selectedEdge.properties.comments as string[]).map((c, i) => (
                                              <li key={i} style={{ lineHeight: 1.4 }}>{c}</li>
                                            ))}
                                          </ul>
                                        )}
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            );
                          })}
                      </div>
                    </>}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Multi-select actions (shown when 2+ nodes are selected) */}
        {selectedNodes.size > 1 && (
          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 13, color: "#94a3b8" }}>{selectedNodes.size} nodes selected</p>
            <div style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}>
              <button
                onClick={handleHideSelected}
                style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
              >
                Hide selected
              </button>
              <button
                onClick={handleShowSelected}
                style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
              >
                Show selected
              </button>
              <button
                onClick={handleShowOnly}
                style={{ padding: "4px 8px", fontSize: 11, background: "#475569", color: "#fff", border: "none", borderRadius: 4, cursor: "pointer" }}
              >
                Show only
              </button>
            </div>
          </div>
        )}

        {/* Standalone relationship panel (shown when a link is clicked with multiple nodes selected) */}
        {selectedEdge && selectedNodes.size !== 1 && (() => {
          const srcName = graphData?.nodes.find(n => n.email === selectedEdge.source)?.name ?? selectedEdge.source;
          const tgtName = graphData?.nodes.find(n => n.email === selectedEdge.target)?.name ?? selectedEdge.target;
          return (
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
              <p style={{ fontSize: 13, color: "#e2e8f0", fontWeight: 600, marginBottom: 4, textAlign: "center" }}>{srcName}</p>
              <p style={{ fontSize: 11, color: "#64748b", marginBottom: 4, textAlign: "center" }}>↕</p>
              <p style={{ fontSize: 13, color: "#e2e8f0", fontWeight: 600, marginBottom: 8, textAlign: "center" }}>{tgtName}</p>
              {selectedEdge.properties.email_count != null && (
                <p style={{ fontSize: 12, color: "#94a3b8", marginBottom: 6 }}>
                  📧 <strong>{selectedEdge.properties.email_count}</strong> emails exchanged
                </p>
              )}
              {selectedEdge.properties.summary ? (
                <p style={{ fontSize: 12, color: "#cbd5e1", lineHeight: 1.5, marginBottom: 10 }}>
                  {selectedEdge.properties.summary}
                </p>
              ) : (
                <button
                  onClick={handleSummarizeEdge}
                  disabled={isSummarizingEdge}
                  style={{
                    width: "100%", padding: "8px", fontSize: 12,
                    background: "#334155", color: "#e2e8f0",
                    border: "1px solid #475569", borderRadius: 6,
                    cursor: isSummarizingEdge ? "wait" : "pointer",
                    marginBottom: 10
                  }}
                >
                  {isSummarizingEdge ? "Generating..." : "Generate Summary"}
                </button>
              )}
              {selectedEdge.properties.comments && (selectedEdge.properties.comments as string[]).length > 0 && (
                <div style={{ marginTop: 8 }}>
                  <button
                    onClick={() => setShowComments(!showComments)}
                    style={{
                      display: "flex", alignItems: "center", gap: 6,
                      background: "none", border: "none", color: "#6366f1",
                      fontSize: 11, fontWeight: 600, cursor: "pointer", padding: 0,
                      marginBottom: 6
                    }}
                  >
                    {showComments ? "▼ Hide observations" : "▶ Show raw observations"}
                    <span style={{ fontSize: 10, color: "#64748b" }}>({(selectedEdge.properties.comments as string[]).length})</span>
                  </button>
                  {showComments && (
                    <ul style={{
                      margin: 0, paddingLeft: 16, fontSize: 11, color: "#94a3b8",
                      display: "flex", flexDirection: "column", gap: 6,
                      maxHeight: 200, overflowY: "auto"
                    }}>
                      {(selectedEdge.properties.comments as string[]).map((c, i) => (
                        <li key={i} style={{ lineHeight: 1.4 }}>{c}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          );
        })()}

        {/* Cluster legend */}
        {!expandedCluster && clusterInfo.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <button
              onClick={() => setShowClustersList(!showClustersList)}
              style={{
                width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
                background: "none", border: "none", padding: 0, marginBottom: 8, cursor: "pointer",
                textAlign: "left"
              }}
            >
              <h3 style={{ fontSize: 13, fontWeight: 600, margin: 0, color: "#94a3b8" }}>Clusters</h3>
              <span style={{ fontSize: 10, color: "#64748b" }}>{showClustersList ? "▼" : "▶"}</span>
            </button>

            {showClustersList && clusterInfo.map(([id, names]) => (
              <div
                key={id}
                onClick={() => handleClusterClick(id)}
                style={{ marginBottom: 6, fontSize: 12, cursor: "pointer" }}
              >
                <span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: CLUSTER_COLORS[id % CLUSTER_COLORS.length], marginRight: 6, verticalAlign: "middle" }} />
                <span style={{ color: expandedCluster === id ? CLUSTER_COLORS[id % CLUSTER_COLORS.length] : "#cbd5e1" }}>
                  {clusterNameMap.get(id) ?? `Cluster ${id}`}
                </span>
                <span style={{ color: "#64748b" }}> ({names.length})</span>
              </div>
            ))}
          </div>
        )}

        {meta && (
          <div>
            <button
              onClick={() => setShowDegreesList(!showDegreesList)}
              style={{
                width: "100%", display: "flex", justifyContent: "space-between", alignItems: "center",
                background: "none", border: "none", padding: 0, marginBottom: 8, cursor: "pointer",
                textAlign: "left"
              }}
            >
              <h3 style={{ fontSize: 13, fontWeight: 600, margin: 0, color: "#94a3b8" }}>People</h3>
              <span style={{ fontSize: 10, color: "#64748b" }}>{showDegreesList ? "▼" : "▶"}</span>
            </button>

            {showDegreesList && (
              <div style={{ marginBottom: 12, padding: "0 4px", display: "flex", alignItems: "center", gap: 8 }}>
                <label style={{ fontSize: 11, color: "#94a3b8", whiteSpace: "nowrap" }}>Min Degree:</label>
                <select
                  value={minDegree}
                  onChange={(e) => {
                    setMinDegree(parseInt(e.target.value, 10));
                    setLayoutSignal(s => s + 1);
                  }}
                  style={{
                    width: 50,
                    padding: "2px 4px",
                    fontSize: 11,
                    background: "#1e293b",
                    color: "#f8fafc",
                    border: "1px solid #334155",
                    borderRadius: 4,
                    outline: "none",
                    cursor: "pointer"
                  }}
                >
                  {Array.from(new Set(meta.degrees.map(d => d.degree)))
                    .sort((a, b) => a - b)
                    .map(deg => (
                      <option key={deg} value={deg}>{deg}</option>
                    ))}
                </select>
              </div>
            )}

            {showDegreesList && (
              <>
                <div style={{ marginBottom: 12 }}>
                  <input
                    type="text"
                    placeholder="Search people (Enter)..."
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        setSearchQuery(searchInput);
                      }
                    }}
                    style={{
                      width: "100%",
                      padding: "6px 10px",
                      fontSize: 12,
                      background: "#1e293b",
                      border: "1px solid #334155",
                      borderRadius: 6,
                      color: "#f8fafc",
                      outline: "none",
                    }}
                  />
                </div>
                <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                  <button
                    onClick={handleShowEverything}
                    style={{ flex: 1, padding: "4px 0", fontSize: 11, background: "#334155", color: "#e2e8f0", border: "1px solid #475569", borderRadius: 4, cursor: "pointer" }}
                  >
                    Show all
                  </button>
                  <button
                    onClick={handleHideEverything}
                    style={{ flex: 1, padding: "4px 0", fontSize: 11, background: "#334155", color: "#e2e8f0", border: "1px solid #475569", borderRadius: 4, cursor: "pointer" }}
                  >
                    Hide all
                  </button>
                </div>
                <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 13 }}>
                  {[...meta.degrees]
                    .filter(d => {
                      if (d.degree < minDegree) return false;
                      if (!searchQuery) return true;
                      const q = searchQuery.toLowerCase();
                      return (d.name?.toLowerCase().includes(q) || d.email.toLowerCase().includes(q));
                    })
                    .sort((a, b) => {
                      const aSelected = selectedNodes.has(a.email);
                      const bSelected = selectedNodes.has(b.email);
                      if (aSelected && !bSelected) return -1;
                      if (!aSelected && bSelected) return 1;
                      return 0;
                    })
                    .map((d) => (
                      <li
                        key={d.email}
                        style={{
                          padding: "4px 0",
                          display: "flex",
                          alignItems: "flex-start",
                          gap: 8,
                          color: selectedNodes.has(d.email) ? "#f97316" : (hiddenNodes.has(d.email) ? "#475569" : "#cbd5e1")
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={!hiddenNodes.has(d.email)}
                          onChange={() => handleToggleVisibility(d.email)}
                          style={{ marginTop: 4, cursor: "pointer" }}
                        />
                        <div
                          onClick={() => handleNodeClick(d.email, false)}
                          style={{ cursor: "pointer", flex: 1 }}
                        >
                          <span style={{ fontWeight: 500 }}>{d.name || d.email}</span>
                          {d.name && d.email && (
                            <span style={{ fontSize: 11, color: "#64748b", display: "block", marginTop: 1 }}>{d.email}</span>
                          )}
                          <span style={{ color: "#64748b" }}> ({d.degree})</span>
                        </div>
                      </li>
                    ))}
                </ul>
              </>
            )}
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
            selectedNodes={selectedNodes}
            onNodeClick={handleNodeClick}
            onNodesSelect={handleNodesSelect}
            onLinkClick={handleLinkClick}
            onBackgroundClick={handleBackgroundClick}
            width={window.innerWidth - 280}
            height={window.innerHeight}
            showClusters={viewMode === "clusters"}
            resetLayoutSignal={layoutSignal}
            boxSelectEnabled={boxSelectMode}
          />
        ) : (
          !error && <p style={{ padding: 40 }}>Loading graph...</p>
        )}
      </main>
    </div>
  );
}
