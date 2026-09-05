(function (global) {
  "use strict";
  var graph = null;
  var payload = { nodes: [], edges: [], counts: {}, headline: "", lazy: false };
  var filterFlag = "";
  var selectedId = "";

  var PALETTE = {
    abandoned: { fill: "#fff4f2", stroke: "#b42318", label: "#7a1f18", shadow: "rgba(180,35,24,.28)" },
    unowned: { fill: "#fff4f2", stroke: "#b42318", label: "#7a1f18", shadow: "rgba(180,35,24,.22)" },
    stale: { fill: "#fff8ed", stroke: "#c47b11", label: "#7a3d11", shadow: "rgba(196,123,17,.22)" },
    undeclared: { fill: "#f4f0f8", stroke: "#6b3fa0", label: "#4a2a70", shadow: "rgba(107,63,160,.2)" },
    writing: { fill: "#eef8f3", stroke: "#087a53", label: "#145c40", shadow: "rgba(8,122,83,.35)" },
    current: { fill: "#ffffff", stroke: "#d5dad8", label: "#23272a", shadow: "transparent" },
  };

  function $(id) { return document.getElementById(id); }
  function text(node, value) { if (node) node.textContent = value == null ? "" : String(value); }
  function GraphCtor() { return global.G6 && (global.G6.Graph || global.G6.default && global.G6.default.Graph); }

  function paint(node) {
    var primary = node.primary || "current";
    var colors = PALETTE[primary] || PALETTE.current;
    var writing = (node.flags || []).indexOf("writing") >= 0;
    var kind = node.kind || "knowledge";
    var width = kind === "gap" || kind === "work" ? 208 : kind === "floor" ? 164 : 188;
    var height = kind === "floor" || kind === "constitution" ? 58 : 86;
    return {
      id: node.id,
      data: node,
      style: {
        size: [width, height],
        fill: colors.fill,
        stroke: writing && primary !== "writing" ? "#087a53" : colors.stroke,
        lineWidth: writing || node.lazy ? 2.2 : 1,
        radius: 12,
        labelText: (node.kindLabel || "") + "\n" + (node.title || node.id) + "\n" + (node.statusLabel || ""),
        labelFill: colors.label,
        labelFontSize: 11,
        labelFontWeight: 600,
        labelPlacement: "center",
        labelWordWrap: true,
        labelMaxWidth: width - 18,
        shadowColor: writing ? PALETTE.writing.shadow : colors.shadow,
        shadowBlur: writing ? 18 : node.lazy ? 10 : 0,
      },
    };
  }

  function visibleNodes() {
    return (payload.nodes || []).filter(function (node) {
      if (!filterFlag) return true;
      return (node.flags || []).indexOf(filterFlag) >= 0 || node.primary === filterFlag;
    });
  }

  function inspect(node) {
    selectedId = node && node.id || "";
    text($("graphInspectTitle"), node ? node.title : "点一张卡");
    text($("graphInspectStatus"), node ? node.statusLabel : "偷懒会以红、橙、紫和发光出现，不会缩在列表里。");
    text($("graphInspectSummary"), node ? node.summary : "");
    text($("graphInspectKind"), node ? node.kindLabel : "—");
    text($("graphInspectProtocol"), node ? (node.protocol || "无") : "—");
    text($("graphInspectDetection"), node ? (node.detection || "无") : "—");
    text($("graphInspectPath"), node ? (node.path || node.writingGoal || "—") : "—");
    var inspector = $("graphInspector");
    if (inspector) inspector.className = "graph-inspector" + (node && node.lazy ? " is-lazy" : "") + (node && (node.flags || []).indexOf("writing") >= 0 ? " is-writing" : "");
  }

  function renderCounts() {
    var counts = payload.counts || {};
    var buttons = document.querySelectorAll("[data-graph-filter]");
    for (var index = 0; index < buttons.length; index += 1) {
      var button = buttons[index];
      var flag = button.getAttribute("data-graph-filter") || "";
      var count = flag ? (counts[flag] || 0) : (counts.nodes || 0);
      var label = button.getAttribute("data-label") || flag;
      button.textContent = label + " " + count;
      button.classList.toggle("is-empty", flag && count === 0);
      button.classList.toggle("is-active", filterFlag === flag);
      button.disabled = Boolean(flag) && count === 0;
    }
    text($("graphHeadline"), payload.headline || "");
    var banner = $("graphBanner");
    if (banner) banner.className = "graph-banner" + (payload.lazy ? " is-lazy" : "");
  }

  function bindFilters() {
    var root = $("graphFilters");
    if (!root || root.getAttribute("data-bound") === "1") return;
    root.setAttribute("data-bound", "1");
    root.addEventListener("click", function (event) {
      var button = event.target.closest("[data-graph-filter]");
      if (!button || button.disabled) return;
      var next = button.getAttribute("data-graph-filter") || "";
      filterFlag = filterFlag === next ? "" : next;
      draw();
    });
  }

  function draw() {
    var Ctor = GraphCtor();
    var mount = $("knowledgeGraph");
    if (!mount) return;
    bindFilters();
    renderCounts();
    var nodes = visibleNodes();
    var ids = {};
    for (var n = 0; n < nodes.length; n += 1) ids[nodes[n].id] = true;
    var edges = (payload.edges || []).filter(function (edge) { return ids[edge.source] && ids[edge.target]; });
    if (!Ctor) {
      mount.textContent = "G6 未能加载，图谱无法显示。";
      inspect(null);
      return;
    }
    if (graph) {
      try { graph.destroy(); } catch (error) {}
      graph = null;
    }
    mount.innerHTML = "";
    if (!nodes.length) {
      mount.textContent = filterFlag ? "这类偷懒目前没有节点。" : "还没有可展开的知识叶。";
      inspect(null);
      return;
    }
    graph = new Ctor({
      container: mount,
      autoFit: "view",
      padding: [28, 28, 28, 28],
      animation: false,
      data: {
        nodes: nodes.map(paint),
        edges: edges.map(function (edge) {
          return { id: edge.id, source: edge.source, target: edge.target, data: edge };
        }),
      },
      node: { type: "rect" },
      edge: {
        type: "quadratic",
        style: { stroke: "#c5cbc9", lineWidth: 1.1, opacity: 0.9 },
      },
      layout: {
        type: "d3-force",
        preventOverlap: true,
        link: { distance: 140, strength: 0.45 },
        manyBody: { strength: -380 },
        collide: { radius: 72 },
      },
      behaviors: ["drag-canvas", "zoom-canvas", "drag-element", "click-select"],
    });
    graph.on("node:click", function (event) {
      var id = event.target && event.target.id;
      var node = nodes.filter(function (item) { return item.id === id; })[0];
      inspect(node || null);
    });
    graph.on("canvas:click", function () { inspect(null); });
    graph.render().then(function () {
      try { graph.fitView(); } catch (error) {}
      if (selectedId && ids[selectedId]) {
        inspect(nodes.filter(function (item) { return item.id === selectedId; })[0]);
      } else {
        inspect(null);
      }
    }).catch(function () {
      try {
        graph.setLayout({ type: "force", preventOverlap: true, nodeStrength: -300, edgeStrength: 0.2 });
        graph.layout();
      } catch (error) {}
    });
  }

  global.AG2CKnowledgeGraph = {
    render: function (next) {
      payload = next && typeof next === "object" ? next : { nodes: [], edges: [], counts: {}, headline: "", lazy: false };
      filterFlag = "";
      selectedId = "";
      draw();
    },
    clear: function () {
      payload = { nodes: [], edges: [], counts: {}, headline: "", lazy: false };
      if (graph) {
        try { graph.destroy(); } catch (error) {}
        graph = null;
      }
      var mount = $("knowledgeGraph");
      if (mount) mount.textContent = "";
      inspect(null);
      renderCounts();
    },
  };
})(window);
