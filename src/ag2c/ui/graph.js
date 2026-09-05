(function (global) {
  "use strict";
  var graph = null;
  var payload = { nodes: [], edges: [], counts: {}, headline: "", lazy: false };
  var filterFlag = "";
  var selectedId = "";
  var searchQuery = "";
  var signature = "";
  var showDirectories = false;
  var RELATIONS = { covers: "管辖", implements: "实现", replaced_by: "被替代为", explains: "归属楼层", governs: "治理", depends_on: "依赖", related_to: "关联", exposes: "暴露空洞" };
  var ISSUES = { "floor-link-missing": "没有连接楼层", "floor-scope-mismatch": "楼层不覆盖实际代码范围", "replacement-missing": "旧实现没有替代者", "retired-code-remains": "标记已退役，但代码仍在", "implementation-check-missing": "没有本实现的检测", "implementation-check-mismatch": "检测属于另一套实现，或仅检查 diff 格式", "entrypoint-missing": "入口缺失或不在管辖范围", "source-outside-target": "源码链接指向项目外", "competing-current-implementations": "同一产品能力有多套当前实现" };

  var PALETTE = {
    abandoned: { fill: "#fff4f2", stroke: "#b42318", label: "#7a1f18", shadow: "rgba(180,35,24,.28)" },
    unowned: { fill: "#fff4f2", stroke: "#b42318", label: "#7a1f18", shadow: "rgba(180,35,24,.22)" },
    stale: { fill: "#fff8ed", stroke: "#c47b11", label: "#7a3d11", shadow: "rgba(196,123,17,.22)" },
    undeclared: { fill: "#f4f0f8", stroke: "#6b3fa0", label: "#4a2a70", shadow: "rgba(107,63,160,.2)" },
    writing: { fill: "#eef8f3", stroke: "#087a53", label: "#145c40", shadow: "rgba(8,122,83,.35)" },
    current: { fill: "#ffffff", stroke: "#d5dad8", label: "#23272a", shadow: "transparent" },
    ambiguous: { fill: "#fff4f2", stroke: "#b42318", label: "#7a1f18", shadow: "transparent" },
    unreviewed: { fill: "#f4f0f8", stroke: "#6b3fa0", label: "#4a2a70", shadow: "transparent" },
    multiple: { fill: "#fff8ed", stroke: "#c47b11", label: "#7a3d11", shadow: "transparent" },
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
    var direct = (payload.nodes || []).filter(function (node) {
      if (node.detailOnly && !showDirectories && !searchQuery) return false;
      var matchesFlag = !filterFlag || (node.flags || []).indexOf(filterFlag) >= 0 || node.primary === filterFlag;
      var haystack = [node.id, node.title, node.path, node.summary, JSON.stringify(node.jurisdiction || {})].join(" ").toLowerCase();
      return matchesFlag && (!searchQuery || haystack.indexOf(searchQuery) >= 0);
    });
    if (!filterFlag && !searchQuery) return direct;
    var ids = {};
    direct.forEach(function (node) { ids[node.id] = true; });
    var neighbors = Object.assign({}, ids);
    (payload.edges || []).forEach(function (edge) {
      if (edge.relation !== "contains" && (ids[edge.source] || ids[edge.target])) { neighbors[edge.source] = true; neighbors[edge.target] = true; }
    });
    return (payload.nodes || []).filter(function (node) { return neighbors[node.id] && (!node.detailOnly || showDirectories || searchQuery); });
  }

  function items(elementId, values) {
    var root = $(elementId);
    if (!root) return;
    root.textContent = "";
    (values.length ? values : ["无记录"]).forEach(function (value) {
      var item = document.createElement("div");
      item.className = "graph-detail-item";
      item.textContent = value;
      root.appendChild(item);
    });
  }

  function revisionText(revisions) {
    return Object.keys(revisions || {}).map(function (target) {
      var value = revisions[target];
      return target + " · " + (value.version || "未声明版本号") + " · " + (value.commit || "无 Git 版本") + (value.dirty_paths ? "（含未提交修改）" : "");
    }).join("\n");
  }

  function choose(id) {
    var node = (payload.nodes || []).filter(function (item) { return item.id === id; })[0];
    inspect(node || null);
    if (graph && node) {
      try { graph.focusElement(id).catch(function () {}); } catch (error) {}
    }
  }

  function inspect(node) {
    selectedId = node && node.id || "";
    text($("graphInspectTitle"), node ? node.title : "点一张卡");
    text($("graphInspectStatus"), node ? node.statusLabel : "选择户口可追查归属、替代者和普查历史。刷新不等于重新普查。");
    text($("graphInspectSummary"), node ? node.summary : "");
    text($("graphInspectKind"), node ? node.kindLabel : "—");
    text($("graphInspectProtocol"), node ? (node.protocol || "无") : "—");
    text($("graphInspectDetection"), node ? (node.detection || "无") : "—");
    text($("graphInspectPath"), node ? (node.path || node.writingGoal || "—") : "—");
    var household = node && node.household || {};
    var declaration = household.jurisdiction || {};
    var census = household.last_census || {};
    if (household.checker_details) text($("graphInspectDetection"), household.checker_details.map(function (checker) { return checker.checker_id + " · " + (checker.implementation || "未绑定实现") + "\n" + JSON.stringify(checker.command); }).join("\n\n") || "未绑定实现检测");
    var freshness = { current: "范围与普查一致", stale: "普查后代码或声明已变化", never: "尚未普查" };
    var lifecycle = { current: "当前主线", legacy: "旧实现待清理", retired: "已退役" };
    text($("graphInspectExcludes"), (household.scopes || []).reduce(function (all, scope) { return all.concat(scope.excludes || []); }, []).join("\n") || "无");
    text($("graphInspectImplementation"), declaration.implementation ? declaration.capability + "\n" + declaration.implementation + " · " + lifecycle[declaration.status] : "非实现户口");
    text($("graphInspectFreshness"), household.freshness ? freshness[household.freshness] + "\n" + (census.surveyed_at || "未记录") + (household.census_age_days !== undefined ? " · " + household.census_age_days + " 天前" : "") : "不适用；请追查关联户口");
    text($("graphInspectVersion"), revisionText(census.project_revisions) || "未记录");
    text($("graphInspectChanged"), (household.last_source_change || []).map(function (change) { return change.changed_at + "\n" + change.commit + "\n" + change.summary; }).join("\n") || "未找到已提交修改");
    text($("graphInspectReview"), census.actor ? census.actor + "\n" + census.reason : "未记录；观察时间不等于审查时间");
    var issues = (household.issues || []).map(function (issue) { return (issue.code === "implementation-check-reused" ? "同一检测命令被贴上不同实现标签" : ISSUES[issue.code] || issue.code) + (issue.path ? "：" + issue.path : "") + (issue.checker ? "：" + issue.checker : ""); });
    (household.signals || []).forEach(function (signal) { issues.push((signal.engine || "前端入口候选") + " → " + signal.path); });
    if ((household.canvas_engines || []).length > 1) issues.unshift("发现多种画布引擎引用：这是并存线索，不自动认定为废代码。");
    items("graphInspectIssues", issues);
    items("graphInspectFiles", (declaration.entrypoints || []).map(function (entry) { return "入口：" + entry; }).concat(household.files || node && node.directory && node.directory.files || []));
    items("graphInspectHistory", (household.history || []).slice().reverse().map(function (entry) { return entry.surveyed_at + " · " + entry.actor + "\n" + revisionText(entry.project_revisions) + "\n" + entry.summary + "\n审查说明：" + entry.reason; }));
    var links = $("graphInspectRelations");
    if (links) {
      links.textContent = "";
      (payload.edges || []).filter(function (edge) { return node && (edge.source === node.id || edge.target === node.id); }).forEach(function (edge) {
        var targetId = edge.source === node.id ? edge.target : edge.source;
        var target = (payload.nodes || []).filter(function (item) { return item.id === targetId; })[0];
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = (edge.source === node.id ? "→ " : "← ") + (RELATIONS[edge.relation] || edge.relation) + "：" + (target && target.title || targetId);
        button.addEventListener("click", function () { choose(targetId); });
        links.appendChild(button);
      });
    }
    if ($("graphNodePicker")) $("graphNodePicker").value = selectedId;
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
    var census = payload.census || {};
    var countsCensus = census.counts || {};
    text($("graphCensusSummary"), census.observed_at ? "目录户口 " + (countsCensus.jurisdictions || 0) + " · 代码文件 " + (countsCensus.code_files || 0) + " · 未认领文件 " + (countsCensus.unowned || 0) + " · 重复认领文件 " + (countsCensus.ambiguous || 0) + " · 门禁：" + (census.required ? "强制" : "观察模式，尚未阻断交付") + "\n当前项目：" + revisionText(census.revisions) : "普查数据尚未加载");
    var banner = $("graphBanner");
    if (banner) banner.className = "graph-banner" + (payload.lazy ? " is-lazy" : "");
  }

  function bindFilters() {
    var root = $("graphFilters");
    if (!root || root.getAttribute("data-bound") === "1") return;
    root.setAttribute("data-bound", "1");
    var searchTimer;
    $("graphSearch").addEventListener("input", function (event) {
      searchQuery = event.target.value.trim().toLowerCase();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(draw, 180);
    });
    $("graphNodePicker").addEventListener("change", function (event) { choose(event.target.value); });
    $("graphShowDirectories").addEventListener("change", function (event) { showDirectories = event.target.checked; draw(); });
    $("graphFit").addEventListener("click", function () { if (graph) graph.fitView(); });
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
    var picker = $("graphNodePicker");
    if (picker) {
      picker.textContent = "";
      [{ id: "", title: "选择一张卡或一个目录" }].concat(nodes).forEach(function (node) {
        var option = document.createElement("option");
        option.value = node.id;
        option.textContent = (node.kindLabel ? node.kindLabel + " · " : "") + node.title;
        picker.appendChild(option);
      });
      picker.value = selectedId;
    }
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
        style: { stroke: "#b2beb8", lineWidth: 1.1, opacity: 0.9, endArrow: true, labelText: function (edge) { var relation = (edge.data || edge).relation; return relation === "contains" ? "包含" : RELATIONS[relation] || relation; }, labelFontSize: 10, labelFill: "#647067", labelBackground: true },
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
      var nextSignature = JSON.stringify([payload.nodes, payload.edges]);
      if (nextSignature === signature && graph) { renderCounts(); choose(selectedId); return; }
      signature = nextSignature;
      draw();
    },
    clear: function () {
      payload = { nodes: [], edges: [], counts: {}, headline: "", lazy: false };
      signature = "";
      filterFlag = "";
      searchQuery = "";
      selectedId = "";
      if ($("graphSearch")) $("graphSearch").value = "";
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
