(function (global) {
  "use strict";
  var payload = { nodes: [], edges: [], combos: [], counts: {}, headline: "", lazy: false };
  var filterFlag = "";
  var selectedId = "";
  var searchQuery = "";
  var signature = "";
  var interacting = false;
  var interactTimer = 0;
  var collapsed = {};
  var RELATIONS = { covers: "覆盖", implements: "实现", replaced_by: "被替代为", explains: "归属楼层", governs: "治理", depends_on: "依赖", related_to: "关联", exposes: "暴露空洞", contains: "包含" };
  var ISSUES = { "floor-link-missing": "没有连接楼层", "floor-scope-mismatch": "楼层不覆盖实际代码范围", "replacement-missing": "旧实现没有替代者", "retired-code-remains": "标记已退役，但代码仍在", "implementation-check-missing": "没有本实现的检测", "implementation-check-mismatch": "检测属于另一套实现，或仅检查 diff 格式", "entrypoint-missing": "入口缺失或不在管辖范围", "source-outside-target": "源码链接指向项目外", "competing-current-implementations": "同一产品能力有多套当前实现", "opaque-claimed": "已挂卡却未点名直接子目录，是黑盒", "undecomposed-directory": "声称说清，但目录未分解", "child-unclaimed": "有未点名的代码子目录", "child-not-proper-subset": "子户口和父户口罩住同一范围", "grain-overflow": "模块档下仍有代码子目录" };

  function $(id) { return document.getElementById(id); }
  function cssId(id) {
    if (global.CSS && CSS.escape) return CSS.escape(id || "");
    return String(id || "").replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }
  function text(node, value) { if (node) node.textContent = value == null ? "" : String(value); }
  function allItems() { return (payload.nodes || []).concat(payload.combos || []); }
  function findItem(id) {
    if (!id) return null;
    var list = allItems();
    for (var i = 0; i < list.length; i += 1) if (list[i].id === id) return list[i];
    return null;
  }
  function markInteracting() {
    interacting = true;
    global.clearTimeout(interactTimer);
    interactTimer = global.setTimeout(function () { interacting = false; }, 5000);
  }

  function filesOf() { return (payload.nodes || []).filter(function (node) { return node.kind === "file" && !node.hidden; }); }
  function cardsOf() { return (payload.nodes || []).filter(function (node) { return (node.kind === "knowledge" || node.kind === "gap" || node.kind === "work") && !node.hidden; }); }
  function dirsOf() { return (payload.combos || []).filter(function (combo) { return combo.kind === "directory"; }); }

  function haystack(item) {
    return [item.id, item.title, item.path, item.summary, item.coverageLabel, item.roleLabel, (item.floors || []).join(" "), (item.coveredBy || []).join(" "), JSON.stringify(item.lastCommit || {})].join(" ").toLowerCase();
  }
  function itemMatches(item) {
    var flagOk = !filterFlag || (item.flags || []).indexOf(filterFlag) >= 0 || item.primary === filterFlag || item.role === filterFlag || (filterFlag === "abandoned" && item.role === "leftover");
    var searchOk = !searchQuery || haystack(item).indexOf(searchQuery) >= 0;
    return flagOk && searchOk;
  }

  function childrenOf(parentId) {
    var dirs = dirsOf().filter(function (combo) { return combo.combo === parentId; });
    var files = filesOf().filter(function (node) { return node.combo === parentId; });
    dirs.sort(function (a, b) { return String(a.title || "").localeCompare(String(b.title || ""), "zh"); });
    files.sort(function (a, b) { return String(a.title || "").localeCompare(String(b.title || ""), "zh"); });
    return dirs.concat(files);
  }

  function descendantMatch(item) {
    if (itemMatches(item)) return true;
    if (item.kind !== "directory") return false;
    var kids = childrenOf(item.id);
    for (var i = 0; i < kids.length; i += 1) if (descendantMatch(kids[i])) return true;
    return false;
  }

  function visibleChildren(parentId) {
    return childrenOf(parentId).filter(function (item) {
      if (!searchQuery && !filterFlag) return true;
      return descendantMatch(item);
    });
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

  function commitText(commit) {
    if (!commit || !commit.changed_at) return "最近 2000 次提交里没有单独记到这个文件";
    return commit.changed_at.replace("T", " ").replace("Z", " UTC") + "\n" + (commit.summary || "") + (commit.commit ? "\n" + commit.commit.slice(0, 12) : "");
  }

  function choose(id, fromUser) {
    if (fromUser) markInteracting();
    selectedId = id || "";
    inspect(findItem(id));
    drawHighlights();
    drawLinks();
    var row = document.querySelector('[data-graph-id="' + cssId(id || "") + '"]');
    if (fromUser && row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
    if ($("graphNodePicker")) $("graphNodePicker").value = selectedId;
  }

  function inspect(node) {
    var kind = node && node.kind || "";
    var isFile = kind === "file" || kind === "directory";
    text($("graphInspectTitle"), node ? node.title : "点文件树或右边的知识卡");
    text($("graphInspectStatus"), node ? (node.roleLabel || node.statusLabel || "") : "左边先把项目文件看清楚。搜 frontend 会只留下前端路径。点一个文件，右边对应的知识卡会亮，线连过去。");
    text($("graphInspectSummary"), node ? node.summary : "");
    text($("graphInspectKind"), node ? node.kindLabel : "—");
    text($("graphInspectProtocol"), node ? (node.protocol || "无") : "—");
    text($("graphInspectDetection"), node ? (node.detection || "无") : "—");
    text($("graphInspectPath"), node ? (node.path || node.writingGoal || "—") : "—");
    text($("graphInspectCoverage"), node ? (isFile ? ((node.coveredBy || []).join("、") || "无知识卡覆盖") : ((node.coversDirectories || []).map(function (path) { return "覆盖 " + path; }).join("\n") || "未覆盖代码目录")) : "点目录看知识卡，点知识卡看目录");
    text($("graphInspectWho"), node ? ((node.coveredBy || []).join("、") || (isFile ? "没有知识卡管理这个文件" : ((node.coversDirectories || []).length ? "它管理 " + node.coversDirectories.join("、") : "没有管理代码目录"))) : "—");
    text($("graphInspectFloors"), node ? ((node.floors || []).join("、") || (isFile ? "没有楼层认领这条路径" : "—")) : "—");
    text($("graphInspectWhen"), node && node.lastCommit ? commitText(node.lastCommit) : (isFile ? "没有单独的提交记录（只表示最近 2000 次提交没点到它，不是文件不存在）" : "—"));
    text($("graphInspectRole"), node ? (node.roleLabel || node.statusLabel || "—") + ((node.replacedBy || []).length ? "\n已被替代为：" + node.replacedBy.join("、") : "") : "—");
    text($("graphInspectUsed"), isFile ? "这版不扫描 import，不能判断这个文件现在有没有被跑到。能判断的是：有没有知识卡认领、卡是当前还是旧实现、有没有替代者、最近一次提交。" : "点左边的文件看单文件情况。");
    var household = node && node.household || {};
    var declaration = household.jurisdiction || {};
    var census = household.last_census || {};
    if (household.checker_details) text($("graphInspectDetection"), household.checker_details.map(function (checker) { return checker.checker_id + " · " + (checker.implementation || "未绑定实现") + "\n" + JSON.stringify(checker.command); }).join("\n\n") || "未绑定实现检测");
    var freshness = { current: "范围与普查一致", stale: "普查后代码或声明已变化", never: "尚未普查" };
    var lifecycle = { current: "当前主线", legacy: "旧实现待清理", retired: "已退役" };
    text($("graphInspectExcludes"), (household.scopes || []).reduce(function (all, scope) { return all.concat(scope.excludes || []); }, []).join("\n") || "无");
    text($("graphInspectImplementation"), declaration.implementation ? declaration.capability + "\n" + declaration.implementation + " · " + lifecycle[declaration.status] : (isFile ? "目录或文件" : "非实现户口"));
    text($("graphInspectFreshness"), household.freshness ? freshness[household.freshness] + "\n" + (census.surveyed_at || "未记录") + (household.census_age_days !== undefined ? " · " + household.census_age_days + " 天前" : "") : "不适用；请追查关联户口");
    text($("graphInspectVersion"), revisionText(census.project_revisions) || "未记录");
    text($("graphInspectChanged"), (household.last_source_change || []).map(function (change) { return change.changed_at + "\n" + change.commit + "\n" + change.summary; }).join("\n") || (node && node.lastCommit ? commitText(node.lastCommit) : "未找到已提交修改"));
    text($("graphInspectReview"), census.actor ? census.actor + "\n" + census.reason : "未记录；观察时间不等于审查时间");
    var issues = (household.issues || []).map(function (issue) { return (issue.code === "implementation-check-reused" ? "同一检测命令被贴上不同实现标签" : ISSUES[issue.code] || issue.code) + (issue.path ? "：" + issue.path : "") + (issue.checker ? "：" + issue.checker : ""); });
    (household.signals || []).forEach(function (signal) { issues.push((signal.engine || "前端入口候选") + " → " + signal.path); });
    if ((household.canvas_engines || []).length > 1) issues.unshift("发现多种画布引擎引用：这是并存线索，不自动认定为废代码。");
    items("graphInspectIssues", issues);
    items("graphInspectFiles", (declaration.entrypoints || []).map(function (entry) { return "入口：" + entry; }).concat(household.files || node && node.files || (kind === "file" ? [node.path || node.summary] : [])));
    items("graphInspectHistory", (household.history || []).slice().reverse().map(function (entry) { return entry.surveyed_at + " · " + entry.actor + "\n" + revisionText(entry.project_revisions) + "\n" + entry.summary + "\n审查说明：" + entry.reason; }));
    var links = $("graphInspectRelations");
    if (links) {
      links.textContent = "";
      (payload.edges || []).filter(function (edge) { return node && (edge.source === node.id || edge.target === node.id); }).forEach(function (edge) {
        if (edge.relation === "covers" && String(edge.target || "").indexOf("file:") === 0 && node && node.kind !== "file") return;
        var targetId = edge.source === node.id ? edge.target : edge.source;
        var target = findItem(targetId);
        var button = document.createElement("button");
        button.type = "button";
        button.textContent = (edge.source === node.id ? "→ " : "← ") + (RELATIONS[edge.relation] || edge.relation) + "：" + (target && target.title || targetId);
        button.addEventListener("click", function () { choose(targetId, true); });
        links.appendChild(button);
      });
    }
    var inspector = $("graphInspector");
    if (inspector) inspector.className = "graph-inspector" + (node && node.lazy ? " is-lazy" : "") + (node && node.role === "leftover" ? " is-lazy" : "") + (node && (node.flags || []).indexOf("writing") >= 0 ? " is-writing" : "");
  }

  function renderCounts() {
    var counts = payload.counts || {};
    var buttons = document.querySelectorAll("[data-graph-filter]");
    for (var index = 0; index < buttons.length; index += 1) {
      var button = buttons[index];
      var flag = button.getAttribute("data-graph-filter") || "";
      var count = flag ? (counts[flag] || 0) : (counts.files || counts.nodes || 0);
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
    if ($("graphSearch")) $("graphSearch").addEventListener("input", function (event) {
      searchQuery = event.target.value.trim().toLowerCase();
      clearTimeout(searchTimer);
      searchTimer = setTimeout(draw, 120);
    });
    if ($("graphNodePicker")) $("graphNodePicker").addEventListener("change", function (event) { choose(event.target.value, true); });
    if ($("graphFit")) $("graphFit").addEventListener("click", function () { collapsed = {}; draw(); });
    root.addEventListener("click", function (event) {
      var button = event.target.closest("[data-graph-filter]");
      if (!button || button.disabled) return;
      var next = button.getAttribute("data-graph-filter") || "";
      filterFlag = filterFlag === next ? "" : next;
      draw();
    });
    var shell = $("knowledgeGraph");
    if (shell) {
      shell.addEventListener("pointerdown", markInteracting);
      shell.addEventListener("wheel", markInteracting, { passive: true });
    }
  }

  function badgeFor(item) {
    if (item.kind === "knowledge") return item.statusLabel || "";
    if ((item.coveredBy || []).length) return item.coveredBy.join("、");
    if (item.kind === "file" || item.kind === "directory") return "无知识卡";
    return "";
  }

  function appendRow(parent, item, depth) {
    var row = document.createElement("button");
    row.type = "button";
    row.className = "graph-tree-row is-" + (item.kind || "file") + (item.role ? " role-" + item.role : "") + (item.id === selectedId ? " is-selected" : "");
    row.setAttribute("data-graph-id", item.id);
    row.style.paddingLeft = (8 + depth * 14) + "px";
    if (item.kind === "directory") {
      var twist = document.createElement("span");
      twist.className = "graph-twist";
      twist.textContent = collapsed[item.id] ? "▸" : "▾";
      twist.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        collapsed[item.id] = !collapsed[item.id];
        draw(true);
      });
      row.appendChild(twist);
    } else {
      var spacer = document.createElement("span");
      spacer.className = "graph-twist";
      spacer.textContent = "·";
      row.appendChild(spacer);
    }
    var name = document.createElement("span");
    name.className = "graph-tree-name";
    name.textContent = item.title || item.id;
    row.appendChild(name);
    var mark = document.createElement("span");
    mark.className = "graph-tree-badge";
    mark.textContent = badgeFor(item);
    row.appendChild(mark);
    row.addEventListener("click", function () { choose(item.id, true); });
    parent.appendChild(row);
    if (item.kind === "directory" && !collapsed[item.id]) {
      visibleChildren(item.id).forEach(function (child) { appendRow(parent, child, depth + 1); });
    }
  }

  function renderChips() {
    var root = $("graphPathChips");
    if (!root) return;
    root.textContent = "";
    visibleChildren("combo:project-dirs").forEach(function (item) {
      if (item.kind !== "directory") return;
      var chip = document.createElement("button");
      chip.type = "button";
      chip.textContent = item.title;
      chip.addEventListener("click", function () {
        collapsed[item.id] = false;
        searchQuery = String(item.title || "").toLowerCase();
        if ($("graphSearch")) $("graphSearch").value = item.title;
        draw();
        choose(item.id, true);
      });
      root.appendChild(chip);
    });
  }

  function renderTree() {
    var root = $("graphTree");
    if (!root) return;
    var keep = root.scrollTop;
    root.textContent = "";
    var kids = visibleChildren("combo:project-dirs");
    if (!kids.length) {
      var empty = document.createElement("div");
      empty.className = "graph-tree-empty";
      empty.textContent = searchQuery || filterFlag ? "没有匹配的文件。清掉搜索或筛选。" : "还没有普查到代码文件。";
      root.appendChild(empty);
    } else {
      kids.forEach(function (item) { appendRow(root, item, 0); });
    }
    root.scrollTop = keep;
  }

  function renderCards() {
    var root = $("graphCards");
    if (!root) return;
    var keep = root.scrollTop;
    root.textContent = "";
    var cards = cardsOf().filter(function (card) {
      if (!filterFlag && !searchQuery) return true;
      if (itemMatches(card)) return true;
      return (payload.edges || []).some(function (edge) {
        if (edge.relation !== "covers" || edge.source !== card.id) return false;
        var target = findItem(edge.target);
        return target && descendantMatch(target);
      });
    });
    if (!cards.length) {
      var empty = document.createElement("div");
      empty.className = "graph-tree-empty";
      empty.textContent = "没有可对照的知识卡。先看左边文件树。";
      root.appendChild(empty);
    }
    cards.forEach(function (card) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "graph-card" + (card.id === selectedId ? " is-selected" : "") + (card.lazy ? " is-lazy" : "");
      button.setAttribute("data-graph-id", card.id);
      var title = document.createElement("strong");
      title.textContent = card.title || card.id;
      var meta = document.createElement("span");
      meta.textContent = (card.statusLabel || "在册") + ((card.coversDirectories || []).length ? " · 覆盖 " + card.coversDirectories.length + " 个目录" : " · 未覆盖代码目录");
      button.appendChild(title);
      button.appendChild(meta);
      if ((card.coversDirectories || []).length) {
        var paths = document.createElement("em");
        paths.textContent = card.coversDirectories.slice(0, 6).join("、");
        button.appendChild(paths);
      }
      button.addEventListener("click", function () { choose(card.id, true); });
      root.appendChild(button);
    });
    root.scrollTop = keep;
  }

  function fillPicker() {
    var picker = $("graphNodePicker");
    if (!picker) return;
    var current = selectedId;
    picker.textContent = "";
    [{ id: "", title: "跳到目录、文件或知识卡", kindLabel: "" }].concat(dirsOf(), filesOf(), cardsOf()).forEach(function (node) {
      var option = document.createElement("option");
      option.value = node.id;
      option.textContent = (node.kindLabel ? node.kindLabel + " · " : "") + (node.title || node.id);
      picker.appendChild(option);
    });
    picker.value = current;
  }

  function coveredIds(cardId) {
    var ids = {};
    (payload.edges || []).forEach(function (edge) {
      if (edge.relation === "covers" && edge.source === cardId) ids[edge.target] = true;
    });
    return ids;
  }

  function drawHighlights() {
    var selected = findItem(selectedId);
    var cover = selected && selected.kind === "knowledge" ? coveredIds(selected.id) : {};
    var owners = {};
    if (selected && (selected.kind === "file" || selected.kind === "directory")) {
      (selected.coveredBy || []).forEach(function (title) {
        cardsOf().forEach(function (card) { if (card.title === title || card.id === title) owners[card.id] = true; });
      });
    }
    document.querySelectorAll("[data-graph-id]").forEach(function (node) {
      var id = node.getAttribute("data-graph-id");
      node.classList.toggle("is-selected", id === selectedId);
      node.classList.toggle("is-linked", Boolean(cover[id] || owners[id]));
    });
  }

  function drawLinks() {
    var svg = $("graphLinks");
    var origin = $("graphSplit");
    if (!svg || !origin) return;
    var width = origin.clientWidth;
    var height = origin.clientHeight;
    svg.setAttribute("viewBox", "0 0 " + width + " " + height);
    svg.setAttribute("width", width);
    svg.setAttribute("height", height);
    svg.innerHTML = "";
    function center(el, side) {
      if (!el) return null;
      var a = el.getBoundingClientRect();
      var b = origin.getBoundingClientRect();
      return {
        x: side === "right" ? a.left - b.left : a.right - b.left,
        y: a.top - b.top + a.height / 2,
      };
    }
    var pairs = [];
    var selected = findItem(selectedId);
    if (selected && selected.kind === "file") {
      cardsOf().forEach(function (card) {
        if ((selected.coveredBy || []).indexOf(card.title) >= 0 || (selected.coveredBy || []).indexOf(card.id) >= 0) {
          pairs.push([selected.id, card.id]);
        }
      });
    } else if (selected && selected.kind === "knowledge") {
      var ids = coveredIds(selected.id);
      document.querySelectorAll("#graphTree [data-graph-id]").forEach(function (row) {
        var id = row.getAttribute("data-graph-id");
        if (ids[id] && pairs.length < 24) pairs.push([id, selected.id]);
      });
    } else {
      cardsOf().forEach(function (card) {
        var ids = coveredIds(card.id);
        var hit = null;
        dirsOf().forEach(function (dir) {
          if (ids[dir.id] && !hit) hit = dir.id;
        });
        if (hit) pairs.push([hit, card.id]);
      });
    }
    pairs.forEach(function (pair) {
      var from = center(document.querySelector('#graphTree [data-graph-id="' + cssId(pair[0]) + '"]'), "left");
      var to = center(document.querySelector('#graphCards [data-graph-id="' + cssId(pair[1]) + '"]'), "right");
      if (!from || !to) return;
      var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      var mid = (from.x + to.x) / 2;
      path.setAttribute("d", "M " + from.x + " " + from.y + " C " + mid + " " + from.y + ", " + mid + " " + to.y + ", " + to.x + " " + to.y);
      path.setAttribute("class", "graph-link" + ((pair[0] === selectedId || pair[1] === selectedId) ? " is-active" : ""));
      svg.appendChild(path);
    });
  }

  function draw(keepSelection) {
    bindFilters();
    renderCounts();
    fillPicker();
    renderChips();
    renderTree();
    renderCards();
    if (!keepSelection) inspect(findItem(selectedId));
    drawHighlights();
    global.requestAnimationFrame(drawLinks);
  }

  function bindScroll() {
    var tree = $("graphTree");
    var cards = $("graphCards");
    if (tree && tree.getAttribute("data-scroll") !== "1") {
      tree.setAttribute("data-scroll", "1");
      tree.addEventListener("scroll", function () { markInteracting(); drawLinks(); });
    }
    if (cards && cards.getAttribute("data-scroll") !== "1") {
      cards.setAttribute("data-scroll", "1");
      cards.addEventListener("scroll", function () { markInteracting(); drawLinks(); });
    }
    if (!bindScroll.resize) {
      bindScroll.resize = true;
      global.addEventListener("resize", function () { drawLinks(); });
    }
  }

  global.AG2CKnowledgeGraph = {
    busy: function () { return interacting; },
    render: function (next) {
      payload = next && typeof next === "object" ? next : { nodes: [], edges: [], combos: [], counts: {}, headline: "", lazy: false };
      if (!payload.combos) payload.combos = [];
      var nextSignature = JSON.stringify([
        (payload.nodes || []).map(function (node) { return [node.id, node.coverageLabel, node.role, node.lastCommit && node.lastCommit.commit]; }),
        (payload.edges || []).map(function (edge) { return edge.id; }),
        (payload.combos || []).map(function (combo) { return [combo.id, combo.coverageLabel, combo.role]; }),
      ]);
      if (nextSignature === signature) {
        renderCounts();
        return;
      }
      signature = nextSignature;
      bindFilters();
      bindScroll();
      draw();
    },
    clear: function () {
      payload = { nodes: [], edges: [], combos: [], counts: {}, headline: "", lazy: false };
      signature = "";
      filterFlag = "";
      searchQuery = "";
      selectedId = "";
      collapsed = {};
      if ($("graphSearch")) $("graphSearch").value = "";
      if ($("graphTree")) $("graphTree").textContent = "";
      if ($("graphCards")) $("graphCards").textContent = "";
      if ($("graphLinks")) $("graphLinks").innerHTML = "";
      inspect(null);
      renderCounts();
    },
  };
})(window);
