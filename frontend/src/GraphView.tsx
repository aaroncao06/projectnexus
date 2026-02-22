import { useCallback, useRef, useEffect, useMemo } from "react";
import ForceGraph2D, {
  type ForceGraphMethods,
  type NodeObject,
  type LinkObject,
} from "react-force-graph-2d";

interface GraphNode {
  id: string;
  name: string;
  cluster?: number;
  isClusterNode?: boolean;
  memberCount?: number;
}

interface GraphLink {
  source: string;
  target: string;
  count?: number;
  summary?: string;
}

const CLUSTER_COLORS = [
  "#6366f1", // indigo
  "#f97316", // orange
  "#22c55e", // green
  "#ec4899", // pink
  "#06b6d4", // cyan
  "#eab308", // yellow
  "#a855f7", // purple
  "#ef4444", // red
  "#14b8a6", // teal
  "#f59e0b", // amber
];

// Softer pastel tints for sticky-note fills (graph tab)
const NOTE_FILLS = [
  "#c7d2fe", // indigo tint
  "#fed7aa", // orange tint
  "#bbf7d0", // green tint
  "#fbcfe8", // pink tint
  "#a5f3fc", // cyan tint
  "#fef08a", // yellow tint
  "#e9d5ff", // purple tint
  "#fecaca", // red tint
  "#99f6e4", // teal tint
  "#fde68a", // amber tint
];

interface Props {
  nodes: GraphNode[];
  links: GraphLink[];
  selectedNode: string | null;
  onNodeClick: (email: string) => void;
  onLinkClick: (source: string, target: string) => void;
  width: number;
  height: number;
  showClusters?: boolean;
}

export default function GraphView({
  nodes,
  links,
  selectedNode,
  onNodeClick,
  onLinkClick,
  width,
  height,
  showClusters = false,
}: Props) {
  const fgRef = useRef<ForceGraphMethods<NodeObject>>(undefined);

  const hasClusterNodes = nodes.some((n) => n.isClusterNode);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;

    if (hasClusterNodes) {
      fg.d3Force("charge")?.strength(-400);
      // More emails between clusters → shorter distance
      fg.d3Force("link")
        ?.distance((link: any) => {
          const count = link.count ?? 1;
          // Invert: high count → short distance, low count → long distance
          // Range roughly 100–300
          return Math.max(100, 300 - count * 1.5);
        });
    } else {
      // Sticky-note nodes need more space
      fg.d3Force("charge")?.strength(-250);
      fg.d3Force("link")
        ?.distance((link: any) => {
          const count = link.count ?? 1;
          return Math.max(60, 200 - count * 0.8);
        });
    }

    fg.d3ReheatSimulation();
  }, [hasClusterNodes]);

  const handleClick = useCallback(
    (node: NodeObject) => {
      if (node.id) onNodeClick(node.id as string);
    },
    [onNodeClick]
  );

  const handleLinkClick = useCallback(
    (link: LinkObject) => {
      const sourceId = typeof link.source === "object" ? (link.source as NodeObject).id as string : link.source as string;
      const targetId = typeof link.target === "object" ? (link.target as NodeObject).id as string : link.target as string;
      onLinkClick(sourceId, targetId);
    },
    [onLinkClick]
  );

  const paintNode = useCallback(
    (node: NodeObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const gNode = node as unknown as GraphNode;
      const label = gNode.name ?? (node.id as string);
      const isSelected = node.id === selectedNode;
      const ci = (gNode.cluster ?? 0) % CLUSTER_COLORS.length;
      const clusterColor = CLUSTER_COLORS[ci];

      if (gNode.isClusterNode) {
        // ── Hexagonal super-node (clusters tab) ──
        const size = 14 + (gNode.memberCount ?? 3) * 1.5;
        const sides = 6;
        ctx.beginPath();
        for (let i = 0; i < sides; i++) {
          const angle = (Math.PI / 3) * i - Math.PI / 6;
          const px = node.x! + size * Math.cos(angle);
          const py = node.y! + size * Math.sin(angle);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        }
        ctx.closePath();
        ctx.fillStyle = clusterColor + "33";
        ctx.fill();
        ctx.strokeStyle = clusterColor;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        const fontSize = Math.max(12, 16) / globalScale;
        ctx.font = `bold ${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = clusterColor;
        ctx.fillText(label, node.x!, node.y!);
      } else if (!showClusters) {
        // ── Sticky-note card (graph tab / cork board) ──
        const noteW = 64 / globalScale;
        const noteH = 52 / globalScale;
        const x = node.x! - noteW / 2;
        const y = node.y! - noteH / 2;
        const noteFill = NOTE_FILLS[ci];
        const cornerFold = 8 / globalScale;

        // Shadow
        ctx.save();
        ctx.shadowColor = "rgba(0,0,0,0.35)";
        ctx.shadowBlur = 6 / globalScale;
        ctx.shadowOffsetX = 2 / globalScale;
        ctx.shadowOffsetY = 3 / globalScale;

        // Note body with folded corner
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + noteW - cornerFold, y);
        ctx.lineTo(x + noteW, y + cornerFold);
        ctx.lineTo(x + noteW, y + noteH);
        ctx.lineTo(x, y + noteH);
        ctx.closePath();
        ctx.fillStyle = noteFill;
        ctx.fill();
        ctx.restore();

        // Folded corner triangle
        ctx.beginPath();
        ctx.moveTo(x + noteW - cornerFold, y);
        ctx.lineTo(x + noteW - cornerFold, y + cornerFold);
        ctx.lineTo(x + noteW, y + cornerFold);
        ctx.closePath();
        ctx.fillStyle = clusterColor + "44";
        ctx.fill();

        // Border
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.lineTo(x + noteW - cornerFold, y);
        ctx.lineTo(x + noteW, y + cornerFold);
        ctx.lineTo(x + noteW, y + noteH);
        ctx.lineTo(x, y + noteH);
        ctx.closePath();
        ctx.strokeStyle = isSelected ? clusterColor : "rgba(0,0,0,0.15)";
        ctx.lineWidth = isSelected ? 2.5 / globalScale : 1 / globalScale;
        ctx.stroke();

        // Selection glow
        if (isSelected) {
          ctx.save();
          ctx.shadowColor = clusterColor;
          ctx.shadowBlur = 10 / globalScale;
          ctx.beginPath();
          ctx.moveTo(x, y);
          ctx.lineTo(x + noteW - cornerFold, y);
          ctx.lineTo(x + noteW, y + cornerFold);
          ctx.lineTo(x + noteW, y + noteH);
          ctx.lineTo(x, y + noteH);
          ctx.closePath();
          ctx.strokeStyle = clusterColor;
          ctx.lineWidth = 2 / globalScale;
          ctx.stroke();
          ctx.restore();
        }

        // Push-pin at top center
        const pinX = node.x!;
        const pinY = y + 1 / globalScale;
        const pinR = 3.5 / globalScale;
        ctx.beginPath();
        ctx.arc(pinX, pinY, pinR, 0, 2 * Math.PI);
        ctx.fillStyle = "#b45309";
        ctx.fill();
        ctx.strokeStyle = "#92400e";
        ctx.lineWidth = 0.8 / globalScale;
        ctx.stroke();
        // Pin highlight
        ctx.beginPath();
        ctx.arc(pinX - 1 / globalScale, pinY - 1 / globalScale, 1.2 / globalScale, 0, 2 * Math.PI);
        ctx.fillStyle = "rgba(255,255,255,0.5)";
        ctx.fill();

        // ── Human silhouette centered on note (behind text) ──
        const silColor = clusterColor + "88";
        const cx = node.x!;
        const cy = node.y!;
        const s = 1 / globalScale;

        // Head
        const headR = 6.5 * s;
        const headY = cy - 8 * s;
        ctx.beginPath();
        ctx.arc(cx, headY, headR, 0, Math.PI * 2);
        ctx.fillStyle = silColor;
        ctx.fill();

        // Shoulders / torso — clip to note bounds
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, noteW, noteH);
        ctx.clip();
        const shoulderW = 14 * s;
        const shoulderH = 10 * s;
        const shoulderY = cy + 4 * s;
        ctx.beginPath();
        ctx.ellipse(cx, shoulderY, shoulderW, shoulderH, 0, Math.PI, 0, true);
        ctx.fillStyle = silColor;
        ctx.fill();
        ctx.restore();

        // ── Name text on top of silhouette ──
        const fontSize = 10 / globalScale;
        ctx.font = `700 ${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = "#1e293b";

        const words = label.split(" ");
        if (words.length > 1) {
          const lineH = fontSize * 1.3;
          ctx.fillText(words[0], cx, cy - lineH / 2);
          ctx.fillText(words.slice(1).join(" "), cx, cy + lineH / 2);
        } else {
          ctx.fillText(label, cx, cy);
        }
      } else {
        // ── Default circle node (clusters tab expanded) ──
        const radius = isSelected ? 8 : 5;
        const fontSize = 14 / globalScale;

        ctx.beginPath();
        ctx.arc(node.x!, node.y!, radius, 0, 2 * Math.PI);
        ctx.fillStyle = isSelected ? "#ffffff" : clusterColor;
        ctx.fill();

        if (isSelected) {
          ctx.strokeStyle = clusterColor;
          ctx.lineWidth = 2;
          ctx.stroke();
        }

        ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "#e2e8f0";
        ctx.fillText(label, node.x!, node.y! + radius + 2);
      }
    },
    [selectedNode, showClusters]
  );

  const paintLinkLabel = useCallback(
    (link: LinkObject, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const src = link.source as NodeObject;
      const tgt = link.target as NodeObject;
      if (!src.x || !src.y || !tgt.x || !tgt.y) return;

      const emailCount = (link as unknown as GraphLink).count;
      if (!emailCount) return;

      const midX = (src.x + tgt.x) / 2;
      const midY = (src.y + tgt.y) / 2;
      const fontSize = 10 / globalScale;

      // Background pill for readability
      const text = `${emailCount}`;
      ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
      const tw = ctx.measureText(text).width;
      const pad = 3 / globalScale;
      ctx.fillStyle = showClusters ? "rgba(15,23,42,0.7)" : "rgba(255,255,255,0.75)";
      ctx.beginPath();
      ctx.roundRect(midX - tw / 2 - pad, midY - fontSize / 2 - pad, tw + pad * 2, fontSize + pad * 2, 3 / globalScale);
      ctx.fill();

      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillStyle = showClusters ? "#94a3b8" : "#5c3a1e";
      ctx.fillText(text, midX, midY);
    },
    [showClusters]
  );

  // ── Generate cork texture once as an offscreen canvas ──
  const corkPattern = useMemo(() => {
    if (showClusters) return null;

    const size = 512;
    const off = document.createElement("canvas");
    off.width = size;
    off.height = size;
    const c = off.getContext("2d")!;

    // Base cork color
    c.fillStyle = "#b5835a";
    c.fillRect(0, 0, size, size);

    // Seeded pseudo-random (deterministic look)
    const rand = (seed: number) => {
      const x = Math.sin(seed * 127.1 + 311.7) * 43758.5453;
      return x - Math.floor(x);
    };

    // Layer 1 — fine grain noise
    for (let i = 0; i < 18000; i++) {
      const x = rand(i * 1.1) * size;
      const y = rand(i * 2.3 + 7) * size;
      const r = rand(i * 3.7 + 13) * 1.8 + 0.3;
      const brightness = rand(i * 5.1 + 19);
      if (brightness < 0.5) {
        c.fillStyle = `rgba(80, 50, 20, ${0.06 + brightness * 0.08})`;
      } else {
        c.fillStyle = `rgba(210, 170, 120, ${0.04 + (brightness - 0.5) * 0.06})`;
      }
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fill();
    }

    // Layer 2 — darker pores / speckles
    for (let i = 0; i < 3000; i++) {
      const x = rand(i * 7.3 + 41) * size;
      const y = rand(i * 11.7 + 59) * size;
      const r = rand(i * 3.1 + 97) * 2.5 + 0.5;
      c.fillStyle = `rgba(60, 35, 10, ${0.08 + rand(i * 13.3) * 0.1})`;
      c.beginPath();
      c.arc(x, y, r, 0, Math.PI * 2);
      c.fill();
    }

    // Layer 3 — subtle lighter streaks (wood fiber)
    for (let i = 0; i < 200; i++) {
      const x = rand(i * 17.1 + 3) * size;
      const y = rand(i * 23.7 + 11) * size;
      const len = rand(i * 31.3 + 29) * 30 + 10;
      const angle = rand(i * 37.1 + 43) * Math.PI;
      c.strokeStyle = `rgba(200, 160, 100, ${0.05 + rand(i * 41.7) * 0.06})`;
      c.lineWidth = rand(i * 47.3) * 1.5 + 0.5;
      c.beginPath();
      c.moveTo(x, y);
      c.lineTo(x + Math.cos(angle) * len, y + Math.sin(angle) * len);
      c.stroke();
    }

    // Layer 4 — very subtle vignette for depth
    const grad = c.createRadialGradient(size / 2, size / 2, size * 0.2, size / 2, size / 2, size * 0.7);
    grad.addColorStop(0, "rgba(0,0,0,0)");
    grad.addColorStop(1, "rgba(0,0,0,0.06)");
    c.fillStyle = grad;
    c.fillRect(0, 0, size, size);

    return off;
  }, [showClusters]);

  // Paint cork texture as tiled background before each frame
  const onRenderFramePre = useCallback(
    (ctx: CanvasRenderingContext2D, _globalScale: number) => {
      if (showClusters || !corkPattern) return;

      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      const pat = ctx.createPattern(corkPattern, "repeat");
      if (pat) {
        ctx.fillStyle = pat;
        ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
      }

      // Subtle darkened border/frame
      const w = ctx.canvas.width;
      const h = ctx.canvas.height;
      const frameGrad = ctx.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.3, w / 2, h / 2, Math.max(w, h) * 0.8);
      frameGrad.addColorStop(0, "rgba(0,0,0,0)");
      frameGrad.addColorStop(1, "rgba(0,0,0,0.15)");
      ctx.fillStyle = frameGrad;
      ctx.fillRect(0, 0, w, h);

      ctx.restore();
    },
    [showClusters, corkPattern]
  );

  return (
    <ForceGraph2D
      ref={fgRef}
      width={width}
      height={height}
      graphData={{ nodes, links }}
      nodeId="id"
      nodeCanvasObject={paintNode}
      onRenderFramePre={showClusters ? undefined : onRenderFramePre as any}
      nodePointerAreaPaint={(node, color, ctx) => {
        const gNode = node as unknown as GraphNode;
        if (gNode.isClusterNode) {
          const hitRadius = 14 + (gNode.memberCount ?? 3) * 1.5;
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, hitRadius, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.fill();
        } else if (!showClusters) {
          // Sticky note hit area
          const s = 35;
          ctx.fillStyle = color;
          ctx.fillRect(node.x! - s, node.y! - s, s * 2, s * 2);
        } else {
          ctx.beginPath();
          ctx.arc(node.x!, node.y!, 8, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.fill();
        }
      }}
      linkColor={() => showClusters ? "#475569" : "#8B4513"}
      linkWidth={(link) => {
        const count = (link as unknown as GraphLink).count ?? 1;
        return Math.min(1 + Math.log2(count), 6);
      }}
      linkCanvasObjectMode={() => "after"}
      linkCanvasObject={paintLinkLabel}
      onNodeClick={handleClick}
      onLinkClick={handleLinkClick}
      linkPointerAreaPaint={(link, color, ctx) => {
        const src = link.source as NodeObject;
        const tgt = link.target as NodeObject;
        if (!src.x || !src.y || !tgt.x || !tgt.y) return;
        ctx.strokeStyle = color;
        ctx.lineWidth = 8;
        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
        ctx.stroke();
      }}
      backgroundColor={showClusters ? "#0f172a" : "#a0764e"}
    />
  );
}
