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
  var currentDetails = null;
  var pickRequestSerial = 0;
  var pickBusy = false;
  var ignoreAddUntil = 0;
  var didResetPageScroll = false;
  var LIST_PREVIEW = 3;
  var evidenceCacheRoot = null;
  var evidenceCacheValue = null;
  var evidenceInFlightRoot = null;

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
    if (value === "protected") return "治理检查已通过";
    if (value === "attention") return "需要处理";
    if (value === "missing") return "目录不可用";
    if (value === "stopped") return "治理已关闭";
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
    if (message === "governance is stopped") return "治理已关闭，项目仍保留在列表中";
    if (message === "canonical worktree has uncommitted changes") return "正式目录里还有没提交的修改，提交或撤掉之后才会恢复正常";
    if (message === "open task worktree has diverged from the canonical branch") return "有施工副本还停在旧的正式提交上，需要刷新或废弃后再继续";
    if (message === "no supported AI harness has a current AG2C Skill") return "还没有检测到可用的 AI Skill 入口";
    if (message.indexOf("runtime") >= 0) return "AG2C 运行时已变化，需要修复交付门禁";
    if (message.indexOf("pre-commit") >= 0 || message.indexOf("hook") >= 0) return "Git 交付门禁需要修复";
    if (message.indexOf("manifest") >= 0 || message.indexOf("project key") >= 0) return "工程的外部治理连接不完整";
    if (message.indexOf("ledger") >= 0 || message.indexOf("evidence") >= 0) return "治理证据需要检查";
    if (message.indexOf("unavailable") >= 0 || message.indexOf("missing") >= 0) return "工程目录或治理数据当前不可用";
    if (message.indexOf("Git is not available") >= 0 || message.indexOf("cannot execute Git") >= 0 || message.indexOf("could not download bundled Git") >= 0) {
      return "本机没有 Git。AG2C 可以下载一份仅自己使用的内置 Git，也可以先安装 Git 并加入 PATH。";
    }
    return message;
  }
  function addProjectError(value) {
    var message = value && value.error ? String(value.error) : "";
    var code = value && value.code ? String(value.code) : "";
    if (message.indexOf("dirty") >= 0 && message.indexOf("enrolling") >= 0) {
      return "这个文件夹里还有没提交的修改。纳入治理不会改你的代码，但未提交改动会被当成异常。请先提交或撤掉，再添加。";
    }
    if (code === "AG2C_STALE_EXTERNAL_STORE" || message.indexOf("AG2C_STALE_EXTERNAL_STORE") >= 0) {
      return "这个项目带着另一台电脑的治理路径，本机没有原来的档案。再添加一次会按本机重新纳入；旧电脑的历史只有把外部档案拷过来才能恢复。";
    }
    if (code === "AG2C_RELOCATED_PROJECT" || message.indexOf("AG2C_RELOCATED_PROJECT") >= 0) {
      return "这个项目的治理档案已在本机找到，但 Git 还指着旧电脑路径。再添加或重新检查一次即可接上。";
    }
    if (code === "AG2C_GIT_MISSING" || message.indexOf("Git is not available") >= 0 || message.indexOf("cannot execute Git") >= 0 || message.indexOf("could not download bundled Git") >= 0) {
      return "本机没有 Git。AG2C 可以下载一份仅自己使用的内置 Git，也可以先安装 Git 并加入 PATH。";
    }
    return requestError(value, "添加项目失败");
  }
  function harnessName(value) {
    if (value === "codex") return "Codex";
    if (value === "claude") return "Claude Code";
    if (value === "cursor") return "Cursor";
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
    if (value === "successful") return "已入库";
    if (value === "abandoned") return "已废弃";
    return "未完成";
  }
  function productStatusName(value) {
    if (value === "checked") return "产品验收已通过";
    if (value === "blocked") return "规则过期，不能当产品通过";
    if (value === "incomplete") return "产品验收还没跑完";
    return "产品验收未登记";
  }
  function cardTypeName(value) {
    if (value === "floor") return "Floor（楼层）";
    if (value === "knowledge") return "Knowledge（知识）";
    if (value === "boundary") return "Boundary（边界）";
    return value || "卡片";
  }
  function yesNo(value, yes, no) {
    return value ? yes : no;
  }
  function timeLabel(value) {
    if (!value) return "";
    return String(value).replace("T", " ").replace(/\.\d+Z?$/, "").replace("Z", "");
  }
  function taskTime(task) {
    if (!task) return "";
    return timeLabel(task.completed_at || (task.result && task.result.completed_at) || task.created_at || "");
  }
  function activeProject() {
    for (var index = 0; index < projects.length; index += 1) if (projects[index].root === selectedRoot) return projects[index];
    return null;
  }
  function selectedIndex() {
    for (var index = 0; index < projects.length; index += 1) if (projects[index].root === selectedRoot) return index;
    return -1;
  }
  function closeFolderPicker() {
    folderRequestSerial += 1;
    pickRequestSerial += 1;
    $("folderDialog").hidden = true;
    ignoreAddUntil = Date.now() + 400;
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
    if ($("selectFolderButton")) $("selectFolderButton").disabled = busy || !folderSelectedIsGit;
    if ($("refreshButton")) $("refreshButton").disabled = busy;
  }
  function setBusy(busy, title, hint) {
    var overlay = $("busyOverlay");
    if (overlay) overlay.hidden = !busy;
    if (busy) {
      if (title) text($("busyTitle"), title);
      if (hint) text($("busyHint"), hint);
      document.body.setAttribute("aria-busy", "true");
    } else {
      document.body.removeAttribute("aria-busy");
    }
    setAddBusy(busy);
  }
  function migrationToast(migrations) {
    var aligned = [];
    var failed = [];
    for (var index = 0; index < (migrations || []).length; index += 1) {
      var item = migrations[index];
      if (item.action === "aligned") aligned.push(item);
      if (item.action === "failed") failed.push(item);
    }
    if (aligned.length) {
      showToast("已将 " + aligned.length + " 个项目对齐到 v" + aligned[0].to_version + "，规则和记录都保留，没有重新切片");
    }
    if (failed.length) showToast("有 " + failed.length + " 个项目未能自动对齐，可点重新检查");
  }
  function openFallbackFolderPicker() {
    $("folderDialog").hidden = false;
    loadFolder(null);
  }
  function isDesktopHost() {
    try {
      if (window.ag2cDesktopHost) return true;
      if (window.external && typeof window.external.IsDesktop === "function" && window.external.IsDesktop()) return true;
    } catch (error) {}
    return false;
  }
  function chooseProject() {
    if (pickBusy || Date.now() < ignoreAddUntil) return;
    if (isDesktopHost()) {
      window.location.href = "ag2c://choose-project";
      return;
    }
    if (window.location.protocol === "http:" || window.location.protocol === "https:") {
      pickBusy = true;
      pickRequestSerial += 1;
      var requestSerial = pickRequestSerial;
      setAddBusy(true);
      showToast("正在打开系统文件夹窗口...");
      request("POST", "/api/filesystem/pick", {}, function (ok, value) {
        pickBusy = false;
        setAddBusy(false);
        if (requestSerial !== pickRequestSerial) return;
        if (!ok) {
          showToast((value && value.error) || "无法打开系统文件夹窗口");
          return;
        }
        if (!value || value.cancelled) return;
        if (value.unavailable) {
          showToast("系统文件夹窗口不可用，已改用应用内选择");
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
      setBusy(false);
      if (!ok) { showToast(requestError(value, "无法读取治理项目")); return; }
      projects = value.projects || [];
      if (!keepSelection || !selectedRoot) selectedRoot = projects.length ? projects[0].root : null;
      if (selectedRoot) {
        var found = false;
        for (var i = 0; i < projects.length; i += 1) if (projects[i].root === selectedRoot) found = true;
        if (!found) selectedRoot = projects.length ? projects[0].root : null;
      }
      if (value.version) text($("engineVersion"), "治理引擎 v" + value.version);
      render();
      migrationToast(value.migrations);
    });
  }
  function projectGlyph(name) {
    var value = String(name || "?");
    return value.slice(0, 2).toUpperCase();
  }
  function projectCard(project) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "project-card" + (project.root === selectedRoot ? " active" : "");
    var glyph = document.createElement("span"); glyph.className = "project-glyph"; glyph.setAttribute("aria-hidden", "true"); text(glyph, projectGlyph(project.name));
    var copy = document.createElement("span"); copy.className = "project-copy";
    var name = document.createElement("strong"); text(name, project.name);
    var path = document.createElement("span"); text(path, project.root);
    var status = document.createElement("span"); status.className = "project-status";
    var dot = document.createElement("span"); dot.className = "project-state " + project.state;
    var badge = document.createElement("span"); text(badge, stateName(project.state));
    status.appendChild(dot); status.appendChild(badge);
    copy.appendChild(name); copy.appendChild(path); copy.appendChild(status);
    button.appendChild(glyph); button.appendChild(copy);
    button.onclick = function () { selectedRoot = project.root; render(); };
    return button;
  }
  function renderProjectDots() {
    var dots = $("projectDots");
    if (!dots) return;
    clear(dots);
    for (var index = 0; index < projects.length; index += 1) {
      var dot = document.createElement("button");
      dot.type = "button";
      dot.className = "project-dot" + (projects[index].root === selectedRoot ? " active" : "");
      dot.setAttribute("aria-label", projects[index].name);
      dot.onclick = (function (root) {
        return function () { selectedRoot = root; render(); };
      }(projects[index].root));
      dots.appendChild(dot);
    }
  }
  function shiftProject(delta) {
    var index = selectedIndex();
    var next = index + delta;
    if (next < 0 || next >= projects.length) return;
    selectedRoot = projects[next].root;
    render();
  }
  function revealSelectedCard() {
    var list = $("projectList");
    if (!list) return;
    var active = list.querySelector(".project-card.active");
    if (!active) return;
    var left = active.offsetLeft;
    var right = left + active.offsetWidth;
    var viewLeft = list.scrollLeft;
    var viewRight = viewLeft + list.clientWidth;
    if (left < viewLeft) list.scrollLeft = Math.max(0, left - 8);
    else if (right > viewRight) list.scrollLeft = right - list.clientWidth + 8;
  }
  function render() {
    var list = $("projectList"); clear(list);
    for (var index = 0; index < projects.length; index += 1) list.appendChild(projectCard(projects[index]));
    text($("projectCount"), projects.length);
    text($("summary"), projects.length ? projects.length + " 个项目正在管理" : "等待添加项目");
    $("emptyState").hidden = projects.length !== 0;
    $("projectRail").hidden = projects.length === 0;
    $("detailPane").hidden = projects.length === 0;
    if ($("projectPrev")) $("projectPrev").disabled = selectedIndex() <= 0;
    if ($("projectNext")) $("projectNext").disabled = selectedIndex() < 0 || selectedIndex() >= projects.length - 1;
    renderProjectDots();
    renderDetail(activeProject());
    window.setTimeout(function () {
      revealSelectedCard();
      if (didResetPageScroll) return;
      didResetPageScroll = true;
      if (window.scrollTo) window.scrollTo(0, 0);
      if (document.documentElement) document.documentElement.scrollTop = 0;
      if (document.body) document.body.scrollTop = 0;
    }, 0);
  }
  function renderDetail(project) {
    $("detailEmpty").hidden = !!project;
    $("detailContent").hidden = !project;
    if (!project) {
      detailRequestSerial += 1;
      renderDetail.shownRoot = null;
      closeListDialog();
      renderDetails(null);
      return;
    }
    try {
      text($("detailName"), project.name);
      text($("detailPath"), project.root);
      $("detailStateDot").className = "state-dot " + project.state;
      var agents = project.agents || [];
      text($("entryState"), agents.length);
      text($("entryHint"), yesNo(project.entry_ready, "已就绪", "未就绪"));
      text($("deliveryState"), yesNo(project.delivery_enforced, "已控制", "未生效"));
      text($("deliveryHint"), project.delivery_enforced ? "交付门禁已接通" : "还没有接通交付门禁");
      text($("observedState"), project.completed_tasks || 0);
      var lastDelivery = project.last_task && project.last_task.delivery;
      text($("observedHint"), lastDelivery && lastDelivery.outcome
        ? lastDelivery.outcome
        : yesNo(project.agent_observed, "已有入库记录", "尚未观察"));
      if ($("healthyCopy")) {
        var productStatus = project.product && project.product.status;
        if (productStatus === "checked") text($("healthyCopy"), "施工检查已通过，产品验收已通过");
        else if (productStatus === "blocked") text($("healthyCopy"), "施工检查已通过，但规则过期，不能当产品通过");
        else if (productStatus === "incomplete") text($("healthyCopy"), "施工检查已通过，产品验收还没跑完");
        else text($("healthyCopy"), "施工检查已通过，产品验收还未登记");
      }
      text($("stateLabel"), stateName(project.state));
      var checked = taskTime(project.last_task);
      text($("healthMeta"), checked ? ("最后检查  " + checked) : "");
      var issueValues = project.issues || [];
      renderPreview($("issueList"), issueValues, issueRow, "需要处理", "");
      if ($("issueList")) $("issueList").hidden = issueValues.length === 0;
      if ($("healthyState")) $("healthyState").hidden = issueValues.length !== 0;
      if ($("detailHealth")) $("detailHealth").className = "detail-health " + project.state;
      if ($("agentList")) $("agentList").hidden = true;
      if ($("evidencePanel")) $("evidencePanel").hidden = true;
      if ($("inspectPanel")) $("inspectPanel").hidden = true;
      if (!project || renderDetail.shownRoot !== project.root) closeListDialog();
      renderDetail.shownRoot = project.root;
      renderAgents(agents);
      renderOverview(project, null);
      clear($("indexFindings"));
      emptyDetail($("pendingList"), "正在读取待更新规则");
      fillStat($("knowledgeList"), "…", "正在读取", "muted");
      fillStat($("relationList"), "…", "正在读取", "muted");
      fillStat($("worktreeList"), "…", "正在读取", "muted");
      loadDetails(project);
      renderEvidenceSummary(project.last_task, project.product);
      renderJournalSummary((currentDetails && currentDetails.journals) || []);
      updateGovernanceActions(project);
      if ($("journalPanel")) $("journalPanel").hidden = true;
    } catch (error) {
      emptyDetail($("cardList"), "页面渲染失败：" + (error && error.message ? error.message : error));
    }
  }
  function renderAgents(agents) {
    var list = $("agentList"); clear(list);
    if (!list) return;
    if (!agents.length) {
      emptyDetail(list, "还没有检测到 Codex、Claude Code、Cursor 或通用 Agent Skills 入口");
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
  function svgNode(name, attributes) {
    var node = document.createElementNS("http://www.w3.org/2000/svg", name);
    for (var key in attributes) if (attributes.hasOwnProperty(key)) node.setAttribute(key, attributes[key]);
    return node;
  }
  function renderRing(passed, warning, failed) {
    var node = $("overviewRing");
    if (!node) return;
    clear(node);
    var total = passed + warning + failed;
    if (!total) { passed = 1; total = 1; }
    var percent = Math.round((passed / total) * 100);
    var radius = 34;
    var circumference = 2 * Math.PI * radius;
    var svg = svgNode("svg", { viewBox: "0 0 96 96", width: "96", height: "96" });
    svg.appendChild(svgNode("circle", { cx: "48", cy: "48", r: String(radius), fill: "none", stroke: "#e5e7eb", "stroke-width": "8" }));
    var offset = 0;
    var parts = [
      { value: passed, color: "#2563eb" },
      { value: warning, color: "#d97706" },
      { value: failed, color: "#dc2626" }
    ];
    for (var index = 0; index < parts.length; index += 1) {
      if (!parts[index].value) continue;
      var length = circumference * (parts[index].value / total);
      var arc = svgNode("circle", {
        cx: "48",
        cy: "48",
        r: String(radius),
        fill: "none",
        stroke: parts[index].color,
        "stroke-width": "8",
        "stroke-linecap": "round",
        "stroke-dasharray": length + " " + circumference,
        "stroke-dashoffset": String(-offset),
        transform: "rotate(-90 48 48)"
      });
      svg.appendChild(arc);
      offset += length;
    }
    node.appendChild(svg);
    var label = document.createElement("div"); label.className = "ring-label";
    var strong = document.createElement("strong"); text(strong, percent + "%");
    var caption = document.createElement("span"); text(caption, failed ? "未通过" : (warning ? "待更新" : "通过"));
    label.appendChild(strong); label.appendChild(caption); node.appendChild(label);
  }
  function metricRow(label, value, tone) {
    var item = document.createElement("div"); item.className = "coverage-metric" + (tone ? " " + tone : "");
    var left = document.createElement("span");
    if (tone) {
      var swatch = document.createElement("span"); swatch.className = "swatch";
      left.appendChild(swatch);
      left.appendChild(document.createTextNode(" " + label));
    } else {
      text(left, label);
    }
    var strong = document.createElement("strong"); text(strong, value);
    item.appendChild(left); item.appendChild(strong); return item;
  }
  function renderOverview(project, details) {
    var metrics = $("coverageMetrics");
    clear(metrics);
    if (!metrics) return;
    var coverage = (details && details.project && details.project.coverage) || (project && project.coverage) || {};
    var pendingCount = (details && details.pending && details.pending.items ? details.pending.items.length : null);
    if (pendingCount === null) pendingCount = (project && project.pending_count) || 0;
    var issueCount = ((project && project.issues) || []).length;
    var checkerCount = coverage.checker_count || 0;
    var passed = issueCount ? 0 : (checkerCount || 1);
    renderRing(passed, pendingCount, issueCount);
    metrics.appendChild(metricRow("通过", passed, "pass"));
    metrics.appendChild(metricRow("警告", pendingCount, "warn"));
    metrics.appendChild(metricRow("失败", issueCount, "fail"));
    var foot = document.createElement("div"); foot.className = "overview-foot";
    var product = (details && details.project && details.project.product) || (project && project.product) || {};
    text(foot, "施工覆盖 " + (coverage.level || "unknown") + "  ·  " + productStatusName(product.status));
    metrics.appendChild(foot);
  }
  function closeListDialog() {
    if ($("listDialog")) $("listDialog").hidden = true;
  }
  function openListDialog(title, fill) {
    var dialog = $("listDialog");
    var body = $("listDialogBody");
    if (!dialog || !body) return;
    text($("listDialogTitle"), title);
    clear(body);
    fill(body);
    dialog.hidden = false;
  }
  function moreButton(count, title, fill) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "more-button";
    text(button, "查看全部 " + count + " 项");
    button.onclick = function (event) {
      if (event && event.stopPropagation) event.stopPropagation();
      openListDialog(title, fill);
    };
    return button;
  }
  function renderPreview(container, items, renderItem, title, emptyText) {
    if (!container) return;
    clear(container);
    if (!items.length) {
      if (emptyText) emptyDetail(container, emptyText);
      return;
    }
    var limit = items.length > LIST_PREVIEW ? LIST_PREVIEW : items.length;
    for (var i = 0; i < limit; i += 1) container.appendChild(renderItem(items[i]));
    if (items.length > LIST_PREVIEW) {
      container.appendChild(moreButton(items.length, title, function (body) {
        for (var j = 0; j < items.length; j += 1) body.appendChild(renderItem(items[j]));
      }));
    }
  }
  function issueRow(message) {
    var item = document.createElement("div");
    item.className = "issue-row";
    text(item, issueName(message));
    return item;
  }
  function findingCard(item) {
    var finding = document.createElement("div");
    finding.className = "index-finding";
    if (item.error) {
      var errorText = document.createElement("p");
      text(errorText, item.error);
      finding.appendChild(errorText);
      return finding;
    }
    var findingHeader = document.createElement("header");
    var findingTitle = document.createElement("strong");
    text(findingTitle, findingName(item.finding_type));
    var findingSeverity = document.createElement("span");
    findingSeverity.className = "index-severity";
    text(findingSeverity, item.severity === "error" ? "需处理" : item.severity);
    findingHeader.appendChild(findingTitle);
    findingHeader.appendChild(findingSeverity);
    finding.appendChild(findingHeader);
    var findingCopy = document.createElement("p");
    text(findingCopy, findingMessage(item.message));
    finding.appendChild(findingCopy);
    return finding;
  }
  function pendingCard(item) {
    var pendingItem = document.createElement("article");
    pendingItem.className = "pending-item";
    var pendingHeader = document.createElement("header");
    var pendingTitle = document.createElement("strong");
    text(pendingTitle, item.title || item.kind);
    var pendingHint = document.createElement("span");
    pendingHint.className = "pending-hint";
    text(pendingHint, item.hint || item.action);
    pendingHeader.appendChild(pendingTitle);
    pendingHeader.appendChild(pendingHint);
    pendingItem.appendChild(pendingHeader);
    var pendingPath = document.createElement("p");
    text(pendingPath, item.path);
    pendingItem.appendChild(pendingPath);
    return pendingItem;
  }
  function emptyDetail(node, message) {
    if (!node) return;
    clear(node);
    var item = document.createElement("div"); item.className = "empty-detail"; text(item, message);
    node.appendChild(item);
  }
  function fillStat(node, primary, secondary, tone) {
    if (!node) return;
    clear(node);
    node.className = "stat-block" + (tone ? " " + tone : "");
    var strong = document.createElement("strong"); text(strong, primary);
    node.appendChild(strong);
    if (secondary) {
      var span = document.createElement("span"); text(span, secondary);
      node.appendChild(span);
    }
  }
  function inspectRow(title, meta, tone) {
    var item = document.createElement("article"); item.className = "inspect-item";
    var header = document.createElement("header");
    var strong = document.createElement("strong"); text(strong, title);
    header.appendChild(strong);
    if (meta) {
      var mark = document.createElement("span"); mark.className = tone || ""; text(mark, meta);
      header.appendChild(mark);
    }
    item.appendChild(header);
    return item;
  }
  function closeInspect() {
    if ($("inspectPanel")) $("inspectPanel").hidden = true;
    closeListDialog();
  }
  function openInspect(kind) {
    var details = currentDetails || {};
    var title = "详情";
    openListDialog(title, function (list) {
      if (kind === "knowledge") {
        text($("listDialogTitle"), "Knowledge");
        var knowledge = details.knowledge || [];
        if (!knowledge.length) emptyDetail(list, "没有 Knowledge 卡片");
        for (var k = 0; k < knowledge.length; k += 1) {
          list.appendChild(inspectRow(knowledge[k].title || knowledge[k].id, knowledgeStatusName(knowledge[k].status), knowledge[k].status));
        }
      } else if (kind === "relations") {
        text($("listDialogTitle"), "契约与关系");
        var relations = details.relations || [];
        var contracts = details.contracts || [];
        if (!relations.length && !contracts.length) emptyDetail(list, "没有契约或关系");
        for (var r = 0; r < relations.length; r += 1) {
          var relationData = relations[r] || {};
          list.appendChild(inspectRow((relationData.source || "?") + "  →  " + (relationData.target || "?"), relationData.type || "explains"));
        }
        for (var q = 0; q < contracts.length; q += 1) {
          var contract = contracts[q];
          list.appendChild(inspectRow(contract.target + ":" + contract.id + "@" + contract.version, "契约"));
        }
      } else if (kind === "worktrees") {
        text($("listDialogTitle"), "施工副本");
        var worktrees = details.worktrees || [];
        if (!worktrees.length) emptyDetail(list, "没有施工副本");
        for (var w = 0; w < worktrees.length; w += 1) {
          var worktree = worktrees[w];
          var lifecycle = (worktree.worktree && worktree.worktree.lifecycle) || worktree.state;
          list.appendChild(inspectRow(worktree.goal || worktree.id, worktreeLifecycleName(lifecycle), lifecycle));
        }
      }
    });
  }
  function renderDetails(details) {
    var project = activeProject();
    clear($("indexFindings")); clear($("pendingList")); clear($("cardList")); clear($("knowledgeList")); clear($("relationList")); clear($("worktreeList"));
    currentDetails = details && details.available ? details : null;
    text($("indexStateLabel"), ""); text($("pendingCountLabel"), ""); text($("cardCountLabel"), ""); text($("contractCountLabel"), ""); text($("worktreeCountLabel"), "");
    if (!details || !details.available) {
      renderOverview(project, null);
      emptyDetail($("pendingList"), "暂无待更新规则");
      emptyDetail($("cardList"), "正在读取治理卡片，或当前还没有详情");
      fillStat($("knowledgeList"), "未知", "还没有 Knowledge", "muted");
      fillStat($("relationList"), "0 个契约", "0 个关系", "muted");
      fillStat($("worktreeList"), "没有副本", "没有进行中的施工", "muted");
      renderJournalSummary((details && details.journals) || []);
      return;
    }
    try {
      renderOverview(project, details);
      var index = details.index || {};
      text($("indexStateLabel"), index.current ? "索引当前" : "索引需要检查");
      text($("cardCountLabel"), (details.cards || []).length + " 张");
      text($("contractCountLabel"), (details.contracts || []).length + " 个契约");
      var findingItems = [];
      var indexErrors = index.errors || [];
      for (var e = 0; e < indexErrors.length; e += 1) findingItems.push({ error: indexErrors[e] });
      var rawFindings = index.findings || [];
      for (var f = 0; f < rawFindings.length; f += 1) findingItems.push(rawFindings[f]);
      renderPreview($("indexFindings"), findingItems, findingCard, "治理概览", findingItems.length ? "" : "没有索引发现");
      var pending = (details.pending && details.pending.items) || (details.project && details.project.pending) || [];
      text($("pendingCountLabel"), pending.length ? pending.length + " 项" : "没有待更新");
      renderPreview($("pendingList"), pending, pendingCard, "待更新规则", "暂无待更新规则");
      var cards = details.cards || [];
      var grouped = {};
      for (var c = 0; c < cards.length; c += 1) {
        var type = cards[c].type || "other";
        if (!grouped[type]) grouped[type] = [];
        grouped[type].push(cards[c]);
      }
      var typeKeys = [];
      var typeOrder = ["floor", "knowledge", "boundary"];
      var seen = {};
      for (var t = 0; t < typeOrder.length; t += 1) {
        if (!grouped[typeOrder[t]]) continue;
        seen[typeOrder[t]] = true;
        typeKeys.push(typeOrder[t]);
      }
      for (var extra in grouped) if (grouped.hasOwnProperty(extra) && !seen[extra]) typeKeys.push(extra);
      renderPreview($("cardList"), typeKeys, function (type) { return typeRow(type, grouped[type]); }, "治理卡片", "没有治理卡片");
      var knowledge = details.knowledge || [];
      if (!knowledge.length) {
        fillStat($("knowledgeList"), "没有卡片", "基线项目可以没有 Knowledge", "muted");
      } else {
        var worst = "current";
        for (var k = 0; k < knowledge.length; k += 1) {
          if (knowledge[k].status === "conflict") worst = "conflict";
          else if (knowledge[k].status === "stale" && worst === "current") worst = "stale";
          else if (knowledge[k].status === "unknown" && worst === "current") worst = "unknown";
        }
        fillStat($("knowledgeList"), knowledgeStatusName(worst), knowledge.length === 1 ? (knowledge[0].title || knowledge[0].id) : (knowledge.length + " 条 Knowledge"), worst);
      }
      var relations = details.relations || [];
      var contracts = details.contracts || [];
      text($("contractCountLabel"), contracts.length + " 个契约");
      fillStat($("relationList"), contracts.length + " 个契约", relations.length + " 个关系", contracts.length || relations.length ? "" : "muted");
      var worktrees = details.worktrees || [];
      var openCount = 0;
      var mergedCount = 0;
      for (var w = 0; w < worktrees.length; w += 1) {
        var lifecycle = (worktrees[w].worktree && worktrees[w].worktree.lifecycle) || worktrees[w].state;
        if (worktrees[w].state === "active" || worktrees[w].state === "verified") openCount += 1;
        if (worktrees[w].state === "completed" || lifecycle === "completed") mergedCount += 1;
      }
      text($("worktreeCountLabel"), openCount ? openCount + " 个进行中" : (mergedCount ? "已合并" : "没有施工副本"));
      if (openCount) fillStat($("worktreeList"), openCount + " 个进行中", worktrees.length + " 条施工记录");
      else if (mergedCount) fillStat($("worktreeList"), "已合并", "无未合并变更", "current");
      else fillStat($("worktreeList"), "没有副本", "没有进行中的施工", "muted");
      renderJournalSummary(details.journals || []);
    } catch (error) {
      renderOverview(project, null);
      emptyDetail($("cardList"), "治理详情无法显示：" + (error && error.message ? error.message : error));
    }
  }
  function typeRow(type, cards) {
    var cardItem = document.createElement("article"); cardItem.className = "governance-card";
    var cardHeader = document.createElement("header");
    var cardTitle = document.createElement("strong"); text(cardTitle, cardTypeName(type));
    var cardType = document.createElement("span"); cardType.className = "card-type"; text(cardType, "已定义 · " + cards.length);
    cardHeader.appendChild(cardTitle); cardHeader.appendChild(cardType); cardItem.appendChild(cardHeader);
    return cardItem;
  }
  function loadDetails(project) {
    var root = project.root;
    detailRequestSerial += 1;
    var requestSerial = detailRequestSerial;
    emptyDetail($("cardList"), "正在读取治理卡片...");
    window.setTimeout(function () {
      if (requestSerial !== detailRequestSerial) return;
      if ($("cardList") && $("cardList").textContent.indexOf("正在读取治理卡片") >= 0) {
        emptyDetail($("cardList"), "治理详情还在读取，点右上角刷新重试");
      }
    }, 8000);
    request("POST", "/api/project/details", { path: project.root }, function (ok, value) {
      if (requestSerial !== detailRequestSerial || selectedRoot !== root) return;
      if (!ok) {
        renderOverview(project, null);
        emptyDetail($("cardList"), value.error || "无法读取治理卡片");
        fillStat($("knowledgeList"), "未知", "无法读取 Knowledge", "muted");
        fillStat($("relationList"), "0 个契约", "0 个关系", "muted");
        fillStat($("worktreeList"), "没有副本", "没有进行中的施工", "muted");
        showToast(requestError(value, "无法读取治理详情"));
        return;
      }
      renderDetails(value);
    });
  }
  function deliveryKindName(value) {
    if (value === "fix") return "修复问题";
    if (value === "feature") return "实现功能";
    if (value === "chore") return "维护改动";
    return "完成改动";
  }
  function renderEvidenceSummary(task, product) {
    if (!task) { fillStat($("evidenceSummary"), "暂无证据", "还没有入库记录", "muted"); return; }
    var status = (product && product.status) || (task.product && task.product.status);
    var delivery = task.delivery || {};
    fillStat(
      $("evidenceSummary"),
      delivery.outcome || "施工已入库",
      (delivery.kind ? deliveryKindName(delivery.kind) + " · " : "") + productStatusName(status),
      status === "checked" ? "current" : "muted"
    );
  }
  function cardActionName(value) {
    if (value === "add") return "新增";
    if (value === "update") return "更新";
    if (value === "remove") return "移除";
    return value || "变更";
  }
  function cardKindName(value) {
    if (value === "floor") return "目录卡";
    if (value === "knowledge") return "Knowledge";
    if (value === "boundary") return "边界卡";
    if (value === "constitution") return "总则";
    return value || "卡片";
  }
  function renderJournalSummary(versions) {
    var node = $("journalSummary");
    if (!node) return;
    if (!versions || !versions.length) {
      fillStat(node, "还没有版本", "完成一次入库后会划定版本日记", "muted");
      return;
    }
    var latest = versions[versions.length - 1];
    var changes = (latest.card_changes || []).length;
    fillStat(node, "v" + latest.version, latest.outcome || (changes ? ("本版改了 " + changes + " 张卡片") : (latest.goal || "本版没有改卡片")), "current");
  }
  function renderJournalList(versions, list) {
    list = list || $("journalList");
    if (!list) return;
    clear(list);
    if (!versions || !versions.length) {
      emptyDetail(list, "还没有治理日志。走完一次开发并入库后，会在这里留下一个版本日记。");
      return;
    }
    for (var index = versions.length - 1; index >= 0; index -= 1) {
      var version = versions[index];
      var item = document.createElement("article");
      item.className = "inspect-item journal-item";
      var header = document.createElement("header");
      var title = document.createElement("strong");
      text(title, "v" + version.version + "  " + (version.outcome || version.goal || "入库版本"));
      var meta = document.createElement("span");
      text(meta, version.marked_at ? String(version.marked_at).replace("T", " ").slice(0, 16) : "");
      header.appendChild(title);
      header.appendChild(meta);
      item.appendChild(header);
      var summary = document.createElement("p");
      var changes = version.card_changes || [];
      var files = version.changed_paths || [];
      text(summary, (files.length ? files.length + " 个文件入库。 " : "") + (changes.length ? "本版改动了 " + changes.length + " 张治理卡片。" : "本版没有改动治理卡片。"));
      item.appendChild(summary);
      if (changes.length) {
        var bullets = document.createElement("ul");
        for (var c = 0; c < changes.length; c += 1) {
          var line = document.createElement("li");
          text(line, cardActionName(changes[c].action) + " " + cardKindName(changes[c].kind) + "：" + (changes[c].title || changes[c].id));
          bullets.appendChild(line);
        }
        item.appendChild(bullets);
      }
      list.appendChild(item);
    }
  }
  function openJournal() {
    var versions = (currentDetails && currentDetails.journals) || [];
    openListDialog("治理日志", function (body) { renderJournalList(versions, body); });
  }
  function updateGovernanceActions(project) {
    var stopped = project && project.state === "stopped";
    if ($("removeButton")) $("removeButton").hidden = !!stopped;
    if ($("resumeButton")) $("resumeButton").hidden = !stopped;
    if ($("stopHint")) {
      text($("stopHint"), stopped
        ? "治理已关闭。项目还在，档案保留。恢复后会重新接通检查。"
        : "停止后项目仍保留，只是不再自动检查。卸载才会清除治理档案。");
    }
    if ($("checkButton")) {
      var label = $("checkButton").querySelector("span:last-child");
      if (label) text(label, stopped ? "恢复治理" : "重新检查");
    }
  }
  function fillEvidenceList(list, tasks) {
    if (!list) return;
    clear(list);
    if (!tasks || !tasks.length) {
      var empty = document.createElement("div");
      empty.className = "evidence-item";
      text(empty, "还没有入库任务");
      list.appendChild(empty);
      return;
    }
    for (var index = 0; index < tasks.length; index += 1) {
      var task = tasks[index];
      var delivery = task.delivery || {};
      var item = document.createElement("article"); item.className = "evidence-item";
      var header = document.createElement("header");
      var title = document.createElement("strong");
      text(title, delivery.outcome || task.goal || task.id);
      var state = document.createElement("span");
      text(state, deliveryKindName(delivery.kind) + " · " + managementName(task.management_result));
      var detail = document.createElement("p");
      var requestLine = (delivery.request && delivery.request !== delivery.outcome)
        ? "需求：" + delivery.request + "。"
        : "";
      text(detail, requestLine + (task.changed_files || []).length + " 个文件，" + (task.checks_passed || 0) + " 项检查通过。 " + productStatusName(task.product && task.product.status));
      header.appendChild(title); header.appendChild(state); item.appendChild(header); item.appendChild(detail); list.appendChild(item);
    }
  }
  function evidenceDialogOpen() {
    return $("listDialog") && !$("listDialog").hidden && $("listDialogTitle") && $("listDialogTitle").textContent === "实际记录";
  }
  function loadEvidence(openPanel) {
    var project = activeProject(); if (!project) return;
    var root = project.root;
    if (openPanel) {
      if (evidenceCacheRoot === root && evidenceCacheValue) {
        openListDialog("实际记录", function (list) {
          fillEvidenceList(list, evidenceCacheValue.tasks || []);
        });
      } else {
        openListDialog("实际记录", function (list) {
          emptyDetail(list, "正在读取实际记录…");
        });
      }
    }
    if (evidenceInFlightRoot === root) return;
    evidenceInFlightRoot = root;
    request("POST", "/api/evidence", { path: project.root }, function (ok, value) {
      if (evidenceInFlightRoot === root) evidenceInFlightRoot = null;
      if (selectedRoot !== root) return;
      if (!ok) {
        if (openPanel && evidenceDialogOpen()) emptyDetail($("listDialogBody"), requestError(value, "无法读取治理记录"));
        showToast(requestError(value, "无法读取治理记录"));
        return;
      }
      evidenceCacheRoot = root;
      evidenceCacheValue = value;
      var tasks = value.tasks || [];
      if ($("evidenceSummary") && tasks.length) {
        renderEvidenceSummary(tasks[0], value.product || tasks[0].product);
      }
      if (openPanel && evidenceDialogOpen()) fillEvidenceList($("listDialogBody"), tasks);
    });
  }
  function addSelectedProject(path, done) {
    if (!path) return;
    setBusy(true, "正在纳入治理", "如需内置 Git 会先下载。请不要关闭窗口");
    request("POST", "/api/projects/add", { path: path }, function (ok, value) {
      if (!ok) {
        setBusy(false);
        showToast(addProjectError(value));
        if (done) done(false);
        return;
      }
      selectedRoot = value.project.root;
      showToast("项目已进入治理");
      refreshProjects(true);
      if (done) done(true);
    });
  }
  function checkSelected() {
    var project = activeProject(); if (!project) return;
    $("checkButton").disabled = true;
    setBusy(true, "正在检查并自动修复", "请稍候，检查过程中请不要关闭窗口");
    request("POST", "/api/projects/check", { path: project.root }, function (ok, value) {
      $("checkButton").disabled = false;
      if (!ok) { setBusy(false); showToast(requestError(value, "检查失败")); return; }
      showToast(value.project.managed ? "治理检查已通过" : "检查发现问题");
      refreshProjects(true);
    });
  }
  function removeSelected() {
    var project = activeProject(); if (!project) return;
    if (!window.confirm("停止治理 “" + project.name + "”？\n\n项目会留在列表里，只是关闭自动检查。治理档案保留。")) return;
    request("POST", "/api/projects/remove", { path: project.root }, function (ok, value) {
      if (!ok) { showToast(requestError(value, "停止治理失败")); return; }
      showToast("已关闭治理，项目仍保留");
      refreshProjects(true);
    });
  }
  function resumeSelected() {
    var project = activeProject(); if (!project) return;
    setBusy(true, "正在恢复治理", "请稍候，恢复过程中请不要关闭窗口");
    request("POST", "/api/projects/resume", { path: project.root }, function (ok, value) {
      if (!ok) { setBusy(false); showToast(requestError(value, "恢复治理失败")); return; }
      showToast(value.project && value.project.managed ? "治理已恢复" : "已尝试恢复治理");
      refreshProjects(true);
    });
  }
  function uninstallSelected() {
    var project = activeProject(); if (!project) return;
    if (!window.confirm("卸载 “" + project.name + "”？\n\n项目文件不会被修改，但外部治理卡片、日志和档案会被清除，且项目会从列表移除。")) return;
    request("POST", "/api/projects/uninstall", { path: project.root }, function (ok, value) {
      if (!ok) { showToast(requestError(value, "卸载失败")); return; }
      selectedRoot = null;
      showToast("项目已卸载，治理档案已清除");
      refreshProjects(false);
    });
  }
  function openEvidence() { loadEvidence(true); }
  function checkOrResume() {
    var project = activeProject();
    if (project && project.state === "stopped") { resumeSelected(); return; }
    checkSelected();
  }
  window.ag2cDesktopHost = false;
  window.ag2cSetDesktopHost = function () { window.ag2cDesktopHost = true; };
  window.ag2cProjectSelected = addSelectedProject;
  window.refreshStatus = function () { refreshProjects(true); };
  $("addButton").onclick = chooseProject;
  $("emptyAddButton").onclick = chooseProject;
  $("closeFolderButton").onclick = closeFolderPicker;
  $("cancelFolderButton").onclick = closeFolderPicker;
  if ($("closeListDialogButton")) $("closeListDialogButton").onclick = closeListDialog;
  if ($("listDialog")) $("listDialog").onclick = function (event) {
    if (event.target === $("listDialog")) closeListDialog();
  };
  $("folderUpButton").onclick = function () { loadFolder(folderParentPath); };
  $("selectFolderButton").onclick = function () {
    if (!folderSelectedPath || !folderSelectedIsGit) return;
    $("selectFolderButton").disabled = true;
    addSelectedProject(folderSelectedPath, function (ok) {
      if (ok) closeFolderPicker(); else $("selectFolderButton").disabled = false;
    });
  };
  $("refreshButton").onclick = function () { refreshProjects(true); };
  $("checkButton").onclick = checkOrResume;
  if ($("journalButton")) $("journalButton").onclick = openJournal;
  if ($("logsButton")) $("logsButton").onclick = openJournal;
  if ($("closeJournalButton")) $("closeJournalButton").onclick = function () { $("journalPanel").hidden = true; };
  if ($("closeEvidenceButton")) $("closeEvidenceButton").onclick = function () { $("evidencePanel").hidden = true; };
  $("removeButton").onclick = removeSelected;
  if ($("resumeButton")) $("resumeButton").onclick = resumeSelected;
  if ($("uninstallButton")) $("uninstallButton").onclick = uninstallSelected;
  $("openFolderButton").onclick = function () { var item = activeProject(); if (item) window.location.href = "ag2c://open-folder?path=" + encodeURIComponent(item.root); };
  if ($("projectPrev")) $("projectPrev").onclick = function () { shiftProject(-1); };
  if ($("projectNext")) $("projectNext").onclick = function () { shiftProject(1); };
  if ($("gateObservedToggle")) $("gateObservedToggle").onclick = function () { loadEvidence(true); };
  if ($("gateAgentsToggle")) $("gateAgentsToggle").onclick = function () {
    var list = $("agentList");
    if (list) list.hidden = !list.hidden;
  };
  if ($("knowledgeCard")) $("knowledgeCard").onclick = function () { openInspect("knowledge"); };
  if ($("relationCard")) $("relationCard").onclick = function () { openInspect("relations"); };
  if ($("worktreeCard")) $("worktreeCard").onclick = function () { openInspect("worktrees"); };
  if ($("closeInspectButton")) $("closeInspectButton").onclick = closeInspect;
  document.onkeydown = function (event) {
    if (event.key !== "Escape") return;
    if ($("busyOverlay") && !$("busyOverlay").hidden) return;
    if ($("listDialog") && !$("listDialog").hidden) { closeListDialog(); return; }
    if (!$("folderDialog").hidden) closeFolderPicker();
  };
  function ensureSession(done) {
    request("GET", "/api/session", null, function (ok, value) {
      if (ok && value && value.token) { saveToken(value.token); done(true); return; }
      done(Boolean(token));
    }, true);
  }
  function loadEngineVersion() {
    request("GET", "/api/status", null, function (ok, value) {
      if (ok && value && value.version) text($("engineVersion"), "治理引擎 v" + value.version);
    });
  }
  ensureSession(function (ok) {
    if (!ok) {
      text($("summary"), "无法连接本地治理服务");
      showToast("无法连接本地治理服务");
    }
    loadEngineVersion();
    setBusy(true, "正在检查并对齐已有项目", "版本更新会保留规则和记录，不会重新切片");
    refreshProjects(false);
  });
}());
