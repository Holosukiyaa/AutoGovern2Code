(function () {
  "use strict";
  var projects = [];
  var selectedRoot = null;
  var token = queryValue("bootstrap");
  var toastTimer = null;

  function $(id) { return document.getElementById(id); }
  function queryValue(name) {
    var parts = window.location.search.replace(/^\?/, "").split("&");
    for (var index = 0; index < parts.length; index += 1) {
      var pair = parts[index].split("=");
      if (decodeURIComponent(pair[0] || "") === name) return decodeURIComponent((pair[1] || "").replace(/\+/g, " "));
    }
    return "";
  }
  function request(method, path, body, done) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, path, true);
    xhr.setRequestHeader("X-AG2C-Token", token);
    if (body !== null) xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var value = null;
      try { value = JSON.parse(xhr.responseText || "null"); } catch (error) { value = { error: xhr.responseText || "请求失败" }; }
      done(xhr.status >= 200 && xhr.status < 300, value);
    };
    xhr.send(body === null ? null : JSON.stringify(body));
  }
  function text(node, value) { node.textContent = value === null || value === undefined ? "" : String(value); }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
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
  function issueName(value) {
    var message = String(value || "");
    if (message === "canonical worktree has uncommitted changes") return "正式工程里有未提交修改，整理干净后才能开始受治理施工";
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
  function yesNo(value, ready, missing) { return value ? ready : missing; }
  function activeProject() {
    for (var index = 0; index < projects.length; index += 1) if (projects[index].root === selectedRoot) return projects[index];
    return null;
  }
  function chooseProject() { window.location.href = "ag2c://choose-project"; }
  function refreshProjects(keepSelection) {
    request("GET", "/api/projects", null, function (ok, value) {
      if (!ok) { showToast(value.error || "无法读取治理项目"); return; }
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
    if (!project) return;
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
    issues.hidden = issueValues.length === 0;
    $("healthyState").hidden = issueValues.length !== 0;
    renderAgents(project.agents || []);
    renderEvidenceSummary(project.last_task);
    $("evidencePanel").hidden = true;
  }
  function renderAgents(agents) {
    var list = $("agentList"); clear(list);
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
  function renderEvidenceSummary(task) {
    var node = $("evidenceSummary"); clear(node);
    if (!task) { var empty = document.createElement("span"); empty.className = "evidence-empty"; text(empty, "暂无治理记录"); node.appendChild(empty); return; }
    var copy = document.createElement("div");
    var title = document.createElement("strong"); text(title, task.goal);
    var meta = document.createElement("span"); text(meta, task.management_result === "successful" ? "验证通过并已交付" : "施工记录尚未完成");
    copy.appendChild(title); copy.appendChild(meta);
    var checks = document.createElement("span"); text(checks, (task.checks_passed || 0) + "/" + (task.checks_run || 0) + " 检查通过");
    node.appendChild(copy); node.appendChild(checks);
  }
  function loadEvidence() {
    var project = activeProject(); if (!project) return;
    request("POST", "/api/evidence", { path: project.root }, function (ok, value) {
      if (!ok) { showToast(value.error || "无法读取治理记录"); return; }
      var panel = $("evidencePanel"); var list = $("evidenceList"); clear(list);
      var tasks = value.tasks || [];
      if (!tasks.length) { var empty = document.createElement("div"); empty.className = "evidence-item"; text(empty, "暂无治理记录"); list.appendChild(empty); }
      for (var index = 0; index < tasks.length; index += 1) {
        var task = tasks[index]; var item = document.createElement("article"); item.className = "evidence-item";
        var header = document.createElement("header"); var title = document.createElement("strong"); text(title, task.goal);
        var state = document.createElement("span"); text(state, task.management_result === "successful" ? "成功" : "未完成");
        var detail = document.createElement("p");
        text(detail, (task.changed_files || []).length + " 个文件，" + (task.checks_passed || 0) + " 项检查通过，失败修正 " + (task.failed_attempts || 0) + " 次");
        header.appendChild(title); header.appendChild(state); item.appendChild(header); item.appendChild(detail); list.appendChild(item);
      }
      panel.hidden = false;
    });
  }
  function addSelectedProject(path) {
    if (!path) return;
    showToast("正在纳入治理...");
    request("POST", "/api/projects/add", { path: path }, function (ok, value) {
      if (!ok) { showToast(value.error || "添加项目失败"); return; }
      selectedRoot = value.project.root;
      showToast("项目已进入治理");
      refreshProjects(true);
    });
  }
  function checkSelected() {
    var project = activeProject(); if (!project) return;
    $("checkButton").disabled = true;
    showToast("正在检查并自动修复...");
    request("POST", "/api/projects/check", { path: project.root }, function (ok, value) {
      $("checkButton").disabled = false;
      if (!ok) { showToast(value.error || "检查失败"); return; }
      showToast(value.project.managed ? "治理检查已通过" : "检查发现问题");
      refreshProjects(true);
    });
  }
  function removeSelected() {
    var project = activeProject(); if (!project) return;
    if (!window.confirm("停止治理 “" + project.name + "”？\n\n项目文件不会被修改，治理记录会保留。")) return;
    request("POST", "/api/projects/remove", { path: project.root }, function (ok, value) {
      if (!ok) { showToast(value.error || "停止治理失败"); return; }
      selectedRoot = null; showToast("项目已停止治理"); refreshProjects(false);
    });
  }
  window.ag2cProjectSelected = addSelectedProject;
  window.refreshStatus = function () { refreshProjects(true); };
  $("addButton").onclick = chooseProject;
  $("emptyAddButton").onclick = chooseProject;
  $("refreshButton").onclick = function () { refreshProjects(true); };
  $("checkButton").onclick = checkSelected;
  $("evidenceButton").onclick = loadEvidence;
  $("closeEvidenceButton").onclick = function () { $("evidencePanel").hidden = true; };
  $("removeButton").onclick = removeSelected;
  $("openFolderButton").onclick = function () { var item = activeProject(); if (item) window.location.href = "ag2c://open-folder?path=" + encodeURIComponent(item.root); };
  refreshProjects(false);
}());
