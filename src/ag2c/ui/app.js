(function () {
  "use strict";
  var projects = [];
  var selectedRoot = null;
  var token = queryValue("bootstrap") || storedToken();
  var toastTimer = null;
  var detailRequestSerial = 0;
  var folderRequestSerial = 0;
  var folderCurrentPath = null;
  var folderParentPath = null;
  var folderSelectedPath = null;
  var folderSelectedIsGit = false;

  function $(id) { return document.getElementById(id); }
  function queryValue(name) {
    var parts = window.location.search.replace(/^\?/, "").split("&");
    for (var index = 0; index < parts.length; index += 1) {
      var pair = parts[index].split("=");
      if (decodeURIComponent(pair[0] || "") === name) return decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
    }
    return "";
  }
  function storedToken() {
    try { return window.sessionStorage.getItem("ag2c-desktop-token") || ""; } catch (error) { return ""; }
  }
  function saveToken(value) {
    token = value;
    try { window.sessionStorage.setItem("ag2c-desktop-token", value); } catch (error) {}
    if (window.history && window.history.replaceState) window.history.replaceState(null, "", "?bootstrap=" + encodeURIComponent(value));
  }
  function requestError(value, fallback) {
    var message = value && value.error ? String(value.error) : "";
    if (message.indexOf("session token") >= 0) return "本地会话已断开，请刷新页面";
    return message || fallback;
  }
  function request(method, path, body, done, retried) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, path, true);
    xhr.setRequestHeader("X-AG2C-Token", token);
    if (body !== null) xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var value = null;
      try { value = JSON.parse(xhr.responseText || "null"); } catch (error) { value = { error: xhr.responseText || "请求失败" }; }
      if (xhr.status === 401 && !retried && path !== "/api/session") {
        request("GET", "/api/session", null, function (sessionOk, sessionValue) {
          if (!sessionOk || !sessionValue || !sessionValue.token) { done(false, value); return; }
          saveToken(sessionValue.token);
          request(method, path, body, done, true);
        }, true);
        return;
      }
      done(xhr.status >= 200 && xhr.status < 300, value);
    };
    xhr.send(body === null ? null : JSON.stringify(body));
  }
  function text(node, value) { if (node) node.textContent = value === null || value === undefined ? "" : String(value); }
  function clear(node) { if (!node) return; while (node.firstChild) node.removeChild(node.firstChild); }
  function showToast(message) {
    var node = $("toast");
    text(node, message);
    node.className = "toast visible";
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { node.className = "toast"; }, 2600);
  }
  function stateName(value) {
    if (value === "protected") return "保护中";
    if (value === "attention") return "需要处理";
    if (value === "missing") return "目录不可用";
    return "未生效";
  }
  function knowledgeStatusName(value) {
    if (value === "current") return "最新";
    if (value === "stale") return "过期";
    if (value === "conflict") return "冲突";
    if (value === "unknown") return "未知";
    if (value === "missing") return "缺失";
    return value || "未知";
  }
  function knowledgeReasonName(value) {
    var message = String(value || "");
    if (message === "reference-digest-changed") return "引用内容已变";
    if (message === "reference-missing") return "引用文件缺失";
    if (message === "not-synced") return "尚未同步";
    if (message === "no-references") return "没有引用";
    if (message.indexOf("assertion-changed:") === 0) return "文档要点已改写";
    if (message.indexOf("assertion-missing:") === 0) return "文档要点找不到";
    return message;
  }
  function findingName(value) {
    if (value === "scope-uncovered") return "未覆盖";
    if (value === "scope-ambiguous") return "归属冲突";
    return value;
  }
  function findingMessage(value) {
    var message = String(value || "");
    var uncovered = message.match(/^No primary floor owns (.+)$/);
    if (uncovered) return "没有目录认领：" + uncovered[1];
    var ambiguous = message.match(/^Multiple primary floors own (.+)$/);
    if (ambiguous) return "多个目录同时认领：" + ambiguous[1];
    return message;
  }
  function issueName(value) {
    var message = String(value || "");
    if (message === "open task worktree has diverged from the canonical branch") return "有施工副本还停在旧的正式提交上，需要刷新或废弃后再继续";
    if (message === "no supported AI harness has a current AG2C Skill") return "还没有检测到可用的 AI Skill 入口";
    if (message.indexOf("runtime") >= 0) return "AG2C 运行时已变化，需要修复交付门禁";
    if (message.indexOf("pre-commit") >= 0 || message.indexOf("hook") >= 0) return "Git 交付门禁需要修复";
    if (message.indexOf("manifest") >= 0 || message.indexOf("project key") >= 0) return "工程的外部治理连接不完整";
    if (message.indexOf("ledger") >= 0 || message.indexOf("evidence") >= 0) return "治理证据需要检查";
    if (message.indexOf("unavailable") >= 0 || message.indexOf("missing") >= 0) return "工程目录或治理数据当前不可用";
    return message;
  }
  function harnessName(value) {
    if (value === "codex") return "Codex";
    if (value === "claude") return "Claude Code";
    if (value === "agents") return "通用 Agent Skills";
    return value;
  }
  function worktreeLifecycleName(value) {
    if (value === "in-progress") return "正在改";
    if (value === "verified-unmerged") return "改完了没合并";
    if (value === "verified-stale") return "验证后有新改动";
    if (value === "diverged") return "正式副本已前进";
    if (value === "missing") return "施工副本丢失";
    if (value === "completed") return "已合并";
    if (value === "abandoned") return "已经废弃";
    return value || "未知";
  }
  function managementName(value) {
    if (value === "successful") return "成功";
    if (value === "abandoned") return "已废弃";
    return "未完成";
  }
  function yesNo(value, yes, no) {
    return value ? yes : no;
  }
  function activeProject() {
    for (var index = 0; index < projects.length; index += 1) if (projects[index].root === selectedRoot) return projects[index];
    return null;
  }
  function closeFolderPicker() {
    folderRequestSerial += 1;
    $("folderDialog").hidden = true;
  }
  function selectFolder(folder, entry) {
    var selected = $("folderList").querySelectorAll(".folder-entry.selected");
    for (var index = 0; index < selected.length; index += 1) {
      selected[index].className = "folder-entry";
      selected[index].setAttribute("aria-selected", "false");
    }
    entry.className = "folder-entry selected";
    entry.setAttribute("aria-selected", "true");
    folderSelectedPath = folder.path;
    folderSelectedIsGit = !!folder.is_git;
    $("selectFolderButton").disabled = !folderSelectedIsGit;
    text($("folderHint"), folderSelectedIsGit ? "已选择 Git 项目：" + folder.path : "此文件夹不是 Git 项目；双击或点右侧箭头继续浏览");
    $("folderHint").className = "folder-hint" + (folderSelectedIsGit ? " ready" : "");
  }
  function folderRow(folder) {
    var entry = document.createElement("div"); entry.className = "folder-entry"; entry.setAttribute("role", "option"); entry.setAttribute("aria-selected", "false");
    var button = document.createElement("button"); button.type = "button"; button.className = "folder-row";
    var icon = document.createElement("span"); icon.className = "folder-icon"; icon.setAttribute("aria-hidden", "true"); text(icon, "\u25a3");
    var name = document.createElement("span"); name.className = "folder-name"; text(name, folder.name);
    button.appendChild(icon); button.appendChild(name);
    if (folder.is_git) { var badge = document.createElement("span"); badge.className = "git-badge"; text(badge, "Git"); button.appendChild(badge); }
    button.onclick = function () { selectFolder(folder, entry); };
    button.ondblclick = function () { loadFolder(folder.path); };
    var open = document.createElement("button"); open.type = "button"; open.className = "folder-open"; open.title = "打开文件夹"; open.setAttribute("aria-label", "打开 " + folder.name); text(open, "\u203a");
    open.onclick = function () { loadFolder(folder.path); };
    entry.appendChild(button); entry.appendChild(open);
    return entry;
  }
  function renderFolder(value) {
    folderCurrentPath = value.path;
    folderParentPath = value.parent;
    folderSelectedPath = value.is_git ? value.path : null;
    folderSelectedIsGit = !!value.is_git;
    text($("folderPath"), value.path || "此电脑");
    $("folderUpButton").disabled = value.path === null;
    $("selectFolderButton").disabled = !folderSelectedIsGit;
    text($("folderHint"), value.is_git ? "当前文件夹是 Git 项目，可以直接选择" : "单击选择文件夹，双击或点右侧箭头打开");
    $("folderHint").className = "folder-hint" + (value.is_git ? " ready" : "");
    var list = $("folderList"); clear(list);
    var directories = value.directories || [];
    for (var index = 0; index < directories.length; index += 1) list.appendChild(folderRow(directories[index]));
    if (!directories.length) emptyDetail(list, "没有可浏览的子文件夹");
    if (value.truncated) showToast("此目录只显示前 1000 个子文件夹");
  }
  function loadFolder(path) {
    folderRequestSerial += 1;
    var requestSerial = folderRequestSerial;
    folderSelectedPath = null;
    folderSelectedIsGit = false;
    $("selectFolderButton").disabled = true;
    text($("folderHint"), "正在读取文件夹...");
    request("POST", "/api/filesystem/list", { path: path }, function (ok, value) {
      if (requestSerial !== folderRequestSerial || $("folderDialog").hidden) return;
      if (!ok) { showToast(requestError(value, "无法读取文件夹")); text($("folderHint"), "无法读取此文件夹"); return; }
      renderFolder(value);
    });
  }
  function setAddBusy(busy) {
    $("addButton").disabled = busy;
    if ($("emptyAddButton")) $("emptyAddButton").disabled = busy;
  }
  function openFallbackFolderPicker() {
    $("folderDialog").hidden = false;
    loadFolder(null);
  }
  function chooseProject() {
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      setAddBusy(true);
      showToast("正在打开系统文件夹窗口...");
      request("POST", "/api/filesystem/pick", {}, function (ok, value) {
        setAddBusy(false);
        if (!ok) {
          showToast((value && value.error) || "无法打开系统文件夹窗口");
          return;
        }
        if (!value || value.cancelled) return;
        if (value.unavailable) {
          openFallbackFolderPicker();
          return;
        }
        if (value.path) {
          if (!value.is_git) {
            showToast("请选择包含 .git 的 Git 项目文件夹");
            return;
          }
          addSelectedProject(value.path);
        }
      });
      return;
    }
    window.location.href = "ag2c://choose-project";
  }
  function refreshProjects(keepSelection) {
    request("GET", "/api/projects", null, function (ok, value) {
      if (!ok) { showToast(requestError(value, "无法读取治理项目")); return; }
      projects = value.projects || [];
      if (!keepSelection || !selectedRoot) selectedRoot = projects.length ? projects[0].root : null;
      if (selectedRoot) {
        var found = false;
        for (var i = 0; i < projects.length; i += 1) if (projects[i].root === selectedRoot) found = true;
        if (!found) selectedRoot = projects.length ? projects[0].root : null;
      }
      render();
    });
  }
  function projectRow(project) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "project-row" + (project.root === selectedRoot ? " active" : "");
    var dot = document.createElement("span"); dot.className = "project-state " + project.state;
    var copy = document.createElement("span"); copy.className = "project-copy";
    var name = document.createElement("strong"); text(name, project.name);
    var path = document.createElement("span"); text(path, project.root);
    copy.appendChild(name); copy.appendChild(path);
    var badge = document.createElement("span"); badge.className = "project-badge"; text(badge, stateName(project.state));
    button.appendChild(dot); button.appendChild(copy); button.appendChild(badge);
    button.onclick = function () { selectedRoot = project.root; render(); };
    return button;
  }
  function render() {
    var list = $("projectList"); clear(list);
    for (var index = 0; index < projects.length; index += 1) list.appendChild(projectRow(projects[index]));
    text($("projectCount"), projects.length);
    text($("summary"), projects.length ? projects.length + " 个项目已登记" : "等待添加项目");
    $("emptyState").hidden = projects.length !== 0;
    list.hidden = projects.length === 0;
    renderDetail(activeProject());
  }
  function renderDetail(project) {
    $("detailEmpty").hidden = !!project;
    $("detailContent").hidden = !project;
    if (!project) { detailRequestSerial += 1; renderDetails(null); return; }
    try {
      text($("detailName"), project.name);
      text($("detailPath"), project.root);
      $("detailStateDot").className = "state-dot " + project.state;
      text($("entryState"), yesNo(project.entry_ready, "已就绪", "未就绪"));
      text($("deliveryState"), yesNo(project.delivery_enforced, "已强制", "未生效"));
      text($("observedState"), yesNo(project.agent_observed, "已有成功记录", "尚未观察"));
      text($("stateLabel"), stateName(project.state));
      var issues = $("issueList"); clear(issues);
      var issueValues = project.issues || [];
      for (var index = 0; index < issueValues.length; index += 1) {
        var item = document.createElement("li"); text(item, issueName(issueValues[index])); issues.appendChild(item);
      }
      if (issues) issues.hidden = issueValues.length === 0;
      if ($("healthyState")) $("healthyState").hidden = issueValues.length !== 0;
      renderAgents(project.agents || []);
      renderOverview(project, null);
      loadDetails(project);
      renderEvidenceSummary(project.last_task);
      loadEvidence();
    } catch (error) {
      emptyDetail($("cardList"), "页面渲染失败：" + (error && error.message ? error.message : error));
    }
  }
  function renderAgents(agents) {
    var list = $("agentList"); clear(list);
    if (!list) return;
    if (!agents.length) {
      emptyDetail(list, "还没有检测到 Codex、Claude Code 或通用 Agent Skills 入口");
      return;
    }
    for (var index = 0; index < agents.length; index += 1) {
      var agent = agents[index];
      var item = document.createElement("div"); item.className = "agent-item " + agent.state;
      var header = document.createElement("header");
      var name = document.createElement("strong"); text(name, harnessName(agent.harness));
      var state = document.createElement("span"); text(state, agent.integrated ? "入口已就绪" : (agent.detected ? "缺少 Skill" : "未检测"));
      var path = document.createElement("p"); text(path, agent.skill_path);
      header.appendChild(name); header.appendChild(state); item.appendChild(header); item.appendChild(path); list.appendChild(item);
    }
  }
  function renderOverview(project, details) {
    var metrics = $("coverageMetrics");
    clear(metrics);
    if (!metrics) return;
    var coverage = (details && details.project && details.project.coverage) || (project && project.coverage) || {};
    var manifest = (details && details.manifest) || {};
    var ledger = (details && details.ledger) || {};
    var targetCount = (manifest.targets || []).length || coverage.area_count || 0;
    var pendingCount = (details && details.pending && details.pending.items ? details.pending.items.length : null);
    if (pendingCount === null) pendingCount = (project && project.pending_count) || 0;
    metrics.appendChild(metric("覆盖级别", coverage.level || "unknown"));
    metrics.appendChild(metric("目标", targetCount));
    metrics.appendChild(metric("待更新", pendingCount));
    if (details) {
      metrics.appendChild(metric("卡片", (details.cards || []).length));
      metrics.appendChild(metric("Ledger 事件", ledger.events === undefined ? "-" : ledger.events));
    } else {
      metrics.appendChild(metric("检查器", coverage.checker_count || 0));
      metrics.appendChild(metric("已完成任务", (project && project.completed_tasks) || 0));
    }
  }
  function emptyDetail(node, message) {
    if (!node) return;
    clear(node);
    var item = document.createElement("div"); item.className = "empty-detail"; text(item, message);
    node.appendChild(item);
  }
  function metric(label, value) {
    var item = document.createElement("div"); item.className = "coverage-metric";
    var strong = document.createElement("strong"); text(strong, value);
    var span = document.createElement("span"); text(span, label);
    item.appendChild(strong); item.appendChild(span); return item;
  }
  function renderDetails(details) {
    var project = activeProject();
    clear($("indexFindings")); clear($("pendingList")); clear($("cardList")); clear($("knowledgeList")); clear($("relationList")); clear($("worktreeList"));
    text($("indexStateLabel"), ""); text($("pendingCountLabel"), ""); text($("cardCountLabel"), ""); text($("contractCountLabel"), ""); text($("worktreeCountLabel"), "");
    if (!details || !details.available) {
      renderOverview(project, null);
      emptyDetail($("pendingList"), "正在读取待更新规则");
      emptyDetail($("cardList"), "正在读取治理卡片，或当前还没有详情");
      emptyDetail($("knowledgeList"), "基线项目默认没有 Knowledge 卡片");
      emptyDetail($("relationList"), "基线项目默认没有契约或关系");
      emptyDetail($("worktreeList"), "没有进行中的施工副本");
      return;
    }
    try {
      renderOverview(project, details);
      var index = details.index || {};
      text($("indexStateLabel"), index.current ? "索引当前" : "索引需要检查");
      text($("cardCountLabel"), (details.cards || []).length + " 张");
      text($("contractCountLabel"), (details.contracts || []).length + " 个契约");
      var findings = $("indexFindings");
      if (index.errors && index.errors.length) {
        for (var e = 0; e < index.errors.length; e += 1) {
          var errorItem = document.createElement("div"); errorItem.className = "index-finding";
          var errorText = document.createElement("p"); text(errorText, index.errors[e]); errorItem.appendChild(errorText); findings.appendChild(errorItem);
        }
      }
      var findingItems = index.findings || [];
      for (var f = 0; f < findingItems.length; f += 1) {
        var finding = document.createElement("div"); finding.className = "index-finding";
        var findingHeader = document.createElement("header");
        var findingTitle = document.createElement("strong"); text(findingTitle, findingName(findingItems[f].finding_type));
        var findingSeverity = document.createElement("span"); findingSeverity.className = "index-severity"; text(findingSeverity, findingItems[f].severity === "error" ? "需处理" : findingItems[f].severity);
        findingHeader.appendChild(findingTitle); findingHeader.appendChild(findingSeverity); finding.appendChild(findingHeader);
        var findingCopy = document.createElement("p"); text(findingCopy, findingMessage(findingItems[f].message)); finding.appendChild(findingCopy); findings.appendChild(finding);
      }
      if (findings && !findings.childNodes.length) emptyDetail(findings, "没有索引发现");
      var pending = (details.pending && details.pending.items) || (details.project && details.project.pending) || [];
      text($("pendingCountLabel"), pending.length ? pending.length + " 项" : "没有待更新");
      var pendingList = $("pendingList");
      for (var p = 0; p < pending.length; p += 1) {
        var pendingItem = document.createElement("article"); pendingItem.className = "pending-item";
        var pendingHeader = document.createElement("header");
        var pendingTitle = document.createElement("strong"); text(pendingTitle, pending[p].title || pending[p].kind);
        var pendingHint = document.createElement("span"); pendingHint.className = "pending-hint"; text(pendingHint, pending[p].hint || pending[p].action);
        pendingHeader.appendChild(pendingTitle); pendingHeader.appendChild(pendingHint); pendingItem.appendChild(pendingHeader);
        var pendingPath = document.createElement("p"); text(pendingPath, pending[p].path); pendingItem.appendChild(pendingPath);
        if (pendingList) pendingList.appendChild(pendingItem);
      }
      if (!pending.length) emptyDetail(pendingList, "合并后没有需要补充的规则");
      var cards = details.cards || []; var cardList = $("cardList");
      for (var c = 0; c < cards.length; c += 1) {
        var card = cards[c]; var cardItem = document.createElement("article"); cardItem.className = "governance-card";
        var cardHeader = document.createElement("header"); var cardTitle = document.createElement("strong"); text(cardTitle, card.title + "  ·  " + card.id);
        var cardType = document.createElement("span"); cardType.className = "card-type"; text(cardType, card.type); cardHeader.appendChild(cardTitle); cardHeader.appendChild(cardType); cardItem.appendChild(cardHeader);
        var cardSummary = document.createElement("p"); text(cardSummary, card.summary); cardItem.appendChild(cardSummary);
        var cardMeta = document.createElement("div"); cardMeta.className = "card-meta";
        var scopes = (card.scopes || []).map(function (scope) {
          return scope.target + ":" + ((scope.include || scope.includes || []).join(", ") || "*");
        }).join("  |  ");
        text(cardMeta, "范围：" + (scopes || "未声明") + "\n检查器：" + ((card.checkers || []).join(", ") || "无") + "\n引用：" + ((card.references || []).join(", ") || "无"));
        cardItem.appendChild(cardMeta); if (cardList) cardList.appendChild(cardItem);
      }
      if (!cards.length) emptyDetail(cardList, "没有治理卡片");
      var knowledge = details.knowledge || []; var knowledgeList = $("knowledgeList");
      for (var k = 0; k < knowledge.length; k += 1) {
        var item = document.createElement("article"); item.className = "knowledge-item";
        var header = document.createElement("header"); var title = document.createElement("strong"); text(title, knowledge[k].title + "  ·  " + knowledge[k].id);
        var status = document.createElement("span"); status.className = "knowledge-status " + knowledge[k].status; text(status, knowledgeStatusName(knowledge[k].status)); header.appendChild(title); header.appendChild(status); item.appendChild(header);
        var reasons = (knowledge[k].reasons || []).map(knowledgeReasonName);
        var meta = document.createElement("div"); meta.className = "knowledge-meta"; text(meta, "来源：" + knowledgeStatusName(knowledge[k].source_status) + "  ·  断言：" + knowledgeStatusName(knowledge[k].assertion_status) + "  ·  " + (reasons.join("，") || "无诊断")); item.appendChild(meta); if (knowledgeList) knowledgeList.appendChild(item);
      }
      if (!knowledge.length) emptyDetail(knowledgeList, "基线项目默认没有 Knowledge 卡片，不影响交付");
      var relations = details.relations || []; var contracts = details.contracts || []; var relationList = $("relationList");
      for (var r = 0; r < relations.length; r += 1) {
        var relation = document.createElement("div"); relation.className = "relation-item";
        var relationHeader = document.createElement("header"); var relationTitle = document.createElement("strong"); text(relationTitle, relation.source + "  →  " + relation.target);
        var relationKind = document.createElement("span"); relationKind.className = "relation-kind"; text(relationKind, relation.type); relationHeader.appendChild(relationTitle); relationHeader.appendChild(relationKind); relation.appendChild(relationHeader);
        if (relationList) relationList.appendChild(relation);
      }
      for (var q = 0; q < contracts.length; q += 1) {
        var contract = document.createElement("div"); contract.className = "relation-item";
        var contractHeader = document.createElement("header"); var contractTitle = document.createElement("strong"); text(contractTitle, contract.target + ":" + contract.id + "@" + contract.version);
        var contractKind = document.createElement("span"); contractKind.className = "relation-kind"; text(contractKind, "contract"); contractHeader.appendChild(contractTitle); contractHeader.appendChild(contractKind); contract.appendChild(contractHeader);
        var contractDetail = document.createElement("p"); text(contractDetail, "边界：" + contract.boundary + "  ·  场景：" + (contract.scenarios || []).join(", ")); contract.appendChild(contractDetail);
        if (relationList) relationList.appendChild(contract);
      }
      if (!relations.length && !contracts.length) emptyDetail(relationList, "基线项目默认没有契约或关系，不影响交付");
      var worktrees = details.worktrees || []; var worktreeList = $("worktreeList");
      var openCount = 0;
      for (var w = 0; w < worktrees.length; w += 1) {
        var worktree = worktrees[w];
        var lifecycle = (worktree.worktree && worktree.worktree.lifecycle) || worktree.state;
        if (worktree.state === "active" || worktree.state === "verified") openCount += 1;
        var worktreeItem = document.createElement("article"); worktreeItem.className = "worktree-item " + lifecycle;
        var worktreeHeader = document.createElement("header");
        var worktreeTitle = document.createElement("strong"); text(worktreeTitle, worktree.goal || worktree.id);
        var worktreeState = document.createElement("span"); worktreeState.className = "worktree-lifecycle"; text(worktreeState, worktreeLifecycleName(lifecycle));
        worktreeHeader.appendChild(worktreeTitle); worktreeHeader.appendChild(worktreeState); worktreeItem.appendChild(worktreeHeader);
        var worktreeMeta = document.createElement("p");
        text(worktreeMeta, (worktree.worktree && worktree.worktree.path) || "施工目录已清理");
        worktreeItem.appendChild(worktreeMeta);
        if (worktreeList) worktreeList.appendChild(worktreeItem);
      }
      text($("worktreeCountLabel"), openCount + " 个进行中");
      if (!worktrees.length) emptyDetail(worktreeList, "没有进行中的施工副本；已合并的任务会留在最近证据里");
    } catch (error) {
      renderOverview(project, null);
      emptyDetail($("cardList"), "治理详情无法显示：" + (error && error.message ? error.message : error));
    }
  }
  function loadDetails(project) {
    var root = project.root;
    detailRequestSerial += 1;
    var requestSerial = detailRequestSerial;
    emptyDetail($("cardList"), "正在读取治理卡片...");
    request("POST", "/api/project/details", { path: project.root }, function (ok, value) {
      if (requestSerial !== detailRequestSerial || selectedRoot !== root) return;
      if (!ok) {
        renderOverview(project, null);
        emptyDetail($("cardList"), value.error || "无法读取治理卡片");
        emptyDetail($("knowledgeList"), "基线项目默认没有 Knowledge 卡片");
        emptyDetail($("relationList"), "基线项目默认没有契约或关系");
        emptyDetail($("worktreeList"), "没有进行中的施工副本");
        showToast(requestError(value, "无法读取治理详情"));
        return;
      }
      renderDetails(value);
    });
  }
  function renderEvidenceSummary(task) {
    var node = $("evidenceSummary"); clear(node);
    if (!task) { var empty = document.createElement("span"); empty.className = "evidence-empty"; text(empty, "暂无治理记录"); node.appendChild(empty); return; }
    var copy = document.createElement("div");
    var title = document.createElement("strong"); text(title, task.goal);
    var meta = document.createElement("span"); text(meta, managementName(task.management_result) === "成功" ? "验证通过并已交付" : (task.management_result === "abandoned" ? "施工副本已废弃" : "施工记录尚未完成"));
    copy.appendChild(title); copy.appendChild(meta);
    var checks = document.createElement("span"); text(checks, (task.checks_passed || 0) + "/" + (task.checks_run || 0) + " 检查通过");
    node.appendChild(copy); node.appendChild(checks);
  }
  function loadEvidence() {
    var project = activeProject(); if (!project) return;
    var root = project.root;
    request("POST", "/api/evidence", { path: project.root }, function (ok, value) {
      if (selectedRoot !== root) return;
      if (!ok) { showToast(requestError(value, "无法读取治理记录")); return; }
      var panel = $("evidencePanel"); var list = $("evidenceList"); clear(list);
      var tasks = value.tasks || [];
      if (!tasks.length) { var empty = document.createElement("div"); empty.className = "evidence-item"; text(empty, "暂无治理记录"); list.appendChild(empty); }
      for (var index = 0; index < tasks.length; index += 1) {
        var task = tasks[index]; var item = document.createElement("article"); item.className = "evidence-item";
        var header = document.createElement("header"); var title = document.createElement("strong"); text(title, task.goal);
        var state = document.createElement("span"); text(state, managementName(task.management_result));
        var detail = document.createElement("p");
        text(detail, (task.changed_files || []).length + " 个文件，" + (task.checks_passed || 0) + " 项检查通过，失败修正 " + (task.failed_attempts || 0) + " 次");
        header.appendChild(title); header.appendChild(state); item.appendChild(header); item.appendChild(detail); list.appendChild(item);
      }
      panel.hidden = false;
    });
  }
  function addSelectedProject(path, done) {
    if (!path) return;
    showToast("正在纳入治理...");
    request("POST", "/api/projects/add", { path: path }, function (ok, value) {
      if (!ok) { showToast(requestError(value, "添加项目失败")); if (done) done(false); return; }
      selectedRoot = value.project.root;
      showToast("项目已进入治理");
      refreshProjects(true);
      if (done) done(true);
    });
  }
  function checkSelected() {
    var project = activeProject(); if (!project) return;
    $("checkButton").disabled = true;
    showToast("正在检查并自动修复...");
    request("POST", "/api/projects/check", { path: project.root }, function (ok, value) {
      $("checkButton").disabled = false;
      if (!ok) { showToast(requestError(value, "检查失败")); return; }
      showToast(value.project.managed ? "治理检查已通过" : "检查发现问题");
      refreshProjects(true);
    });
  }
  function removeSelected() {
    var project = activeProject(); if (!project) return;
    if (!window.confirm("停止治理 “" + project.name + "”？\n\n项目文件不会被修改，治理记录会保留。")) return;
    request("POST", "/api/projects/remove", { path: project.root }, function (ok, value) {
      if (!ok) { showToast(requestError(value, "停止治理失败")); return; }
      selectedRoot = null; showToast("项目已停止治理"); refreshProjects(false);
    });
  }
  window.ag2cProjectSelected = addSelectedProject;
  window.refreshStatus = function () { refreshProjects(true); };
  $("addButton").onclick = chooseProject;
  $("emptyAddButton").onclick = chooseProject;
  $("closeFolderButton").onclick = closeFolderPicker;
  $("cancelFolderButton").onclick = closeFolderPicker;
  $("folderUpButton").onclick = function () { loadFolder(folderParentPath); };
  $("selectFolderButton").onclick = function () {
    if (!folderSelectedPath || !folderSelectedIsGit) return;
    $("selectFolderButton").disabled = true;
    addSelectedProject(folderSelectedPath, function (ok) {
      if (ok) closeFolderPicker(); else $("selectFolderButton").disabled = false;
    });
  };
  $("refreshButton").onclick = function () { refreshProjects(true); };
  $("checkButton").onclick = checkSelected;
  $("evidenceButton").onclick = loadEvidence;
  $("closeEvidenceButton").onclick = function () { $("evidencePanel").hidden = true; };
  $("removeButton").onclick = removeSelected;
  $("openFolderButton").onclick = function () { var item = activeProject(); if (item) window.location.href = "ag2c://open-folder?path=" + encodeURIComponent(item.root); };
  document.onkeydown = function (event) { if (event.key === "Escape" && !$("folderDialog").hidden) closeFolderPicker(); };
  function ensureSession(done) {
    request("GET", "/api/session", null, function (ok, value) {
      if (ok && value && value.token) { saveToken(value.token); done(true); return; }
      done(Boolean(token));
    }, true);
  }
  ensureSession(function (ok) {
    if (!ok) {
      text($("summary"), "无法连接本地治理服务");
      showToast("无法连接本地治理服务");
    }
    refreshProjects(false);
  });
}());
