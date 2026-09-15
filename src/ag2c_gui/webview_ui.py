"""WebView2 壳的 HTML/CSS/JS 字节。首页三区要你处理/系统警情/记录。"""

from __future__ import annotations

UI_INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-Hans">
<head>
<meta charset="utf-8">
<title>AutoGovern2Code</title>
<link rel="stylesheet" href="/ui/layout.css">
</head>
<body>
<header id="bar">
  <div class="brand">AutoGovern2Code</div>
  <label class="field">项目
    <select id="project"></select>
  </label>
  <button type="button" id="add-project">添加项目</button>
  <button type="button" id="refresh">刷新</button>
  <span id="gate" class="gate"></span>
  <span id="status" class="status"></span>
</header>
<nav id="tree">
  <h2>文件</h2>
  <input id="tree-filter" type="search" placeholder="筛选路径或卡片">
  <ul></ul>
</nav>
<main id="home">
  <p id="attention" class="hero">加载中…</p>
  <section id="custody">
    <header class="zone-head"><h2>看 / 否 / 授</h2><span id="custody-head" class="muted"></span></header>
    <p id="custody-irreversible" class="muted"></p>
    <div id="custody-flags" class="flags"></div>
    <ul id="custody-veto"></ul>
    <p class="empty">加载中…</p>
  </section>
  <section id="action">
    <header class="zone-head"><h2>要你处理</h2><button type="button" data-copy="actions">复制给 AI</button></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
  <section id="alert">
    <header class="zone-head"><h2>系统警情</h2><button type="button" data-copy="alerts">复制给 AI</button></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
  <section id="record">
    <header class="zone-head"><h2>记录</h2></header>
    <ul></ul>
    <p class="empty">加载中…</p>
  </section>
</main>
<aside id="inspect">
  <h2>检查器</h2>
  <p id="inspect-title">点文件树或知识卡</p>
  <dl id="inspect-fields"></dl>
</aside>
<footer id="ops">
  <div class="tabs">
    <button type="button" data-tab="audit">操作日志</button>
    <button type="button" data-tab="worktrees">施工</button>
    <button type="button" data-tab="records">实际记录</button>
    <button type="button" data-tab="gate">AI 入口</button>
    <button type="button" id="copy-ops">复制</button>
  </div>
  <div id="ops-body" class="ops-panel"></div>
</footer>
<script src="/ui/app.js"></script>
</body>
</html>
"""

UI_LAYOUT_CSS = """:root {
  --danger: #f24c40;
  --decision: #f2b340;
  --notice: #b38738;
  --ok: #66946b;
  --muted: #8a8a92;
  --bg: #161618;
  --panel: #1e1e22;
  --fg: #ececec;
  --line: #2c2c32;
  --hover: #26262c;
}
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; background: var(--bg); color: var(--fg); font: 14px/1.45 "Segoe UI", "Microsoft YaHei", sans-serif; }
body {
  display: grid;
  grid-template:
    "bar bar bar" auto
    "tree home inspect" 1fr
    "ops ops ops" minmax(10rem, 30%)
    / 42% 1fr 32%;
}
button, select, input {
  font: inherit;
  color: var(--fg);
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 4px;
}
button { cursor: pointer; padding: 0.25rem 0.7rem; }
button:hover, select:hover { background: var(--hover); }
#bar {
  grid-area: bar;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.55rem 0.9rem;
  border-bottom: 1px solid var(--line);
  background: #121214;
}
.brand { font-weight: 650; letter-spacing: 0.02em; }
.field { display: flex; align-items: center; gap: 0.4rem; color: var(--muted); }
.field select { min-width: 18rem; padding: 0.2rem 0.4rem; }
.gate.warn { color: var(--danger); }
.gate { color: var(--ok); }
.status { margin-left: auto; color: var(--muted); font-size: 0.85rem; }
#tree, #inspect { background: var(--panel); overflow: auto; padding: 0.7rem 0.8rem; }
#tree { grid-area: tree; border-right: 1px solid var(--line); }
#inspect { grid-area: inspect; border-left: 1px solid var(--line); }
#home { grid-area: home; overflow: auto; padding: 0.4rem 0 1rem; }
#ops { grid-area: ops; border-top: 1px solid var(--line); background: #121214; display: flex; flex-direction: column; min-height: 0; }
h2 { color: var(--muted); font-size: 0.78rem; font-weight: 650; letter-spacing: 0.08em; text-transform: none; margin: 0 0 0.45rem; }
#tree-filter { width: 100%; margin-bottom: 0.55rem; padding: 0.3rem 0.45rem; }
#tree ul, #home ul { list-style: none; margin: 0; padding: 0; }
#tree li {
  padding: 0.28rem 0.4rem;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
#tree li:hover, #tree li.active { background: var(--hover); }
.hero {
  margin: 0.7rem 1rem 0.4rem;
  font-size: 1.45rem;
  font-weight: 650;
  line-height: 1.25;
}
section { padding: 0.55rem 1rem 0.2rem; }
.zone-head { display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; margin-bottom: 0.35rem; }
.zone-head h2 { margin: 0; }
#home li { padding: 0.35rem 0; border-bottom: 1px solid var(--line); }
#home li.error { color: var(--danger); }
#home li.warn { color: var(--decision); }
#home li.ok { color: var(--ok); }
.empty { color: var(--muted); margin: 0.2rem 0 0.6rem; }
section.is-ready:not(.is-empty) .empty { display: none; }
section.is-ready.is-empty ul { display: none; }
#inspect-title { margin: 0 0 0.6rem; font-weight: 650; }
#inspect-fields { margin: 0; }
#inspect-fields dt { color: var(--muted); font-size: 0.75rem; margin-top: 0.55rem; }
#inspect-fields dd { margin: 0.15rem 0 0; }
.tabs { display: flex; gap: 0.35rem; padding: 0.45rem 0.75rem; border-bottom: 1px solid var(--line); }
.tabs button[data-tab].on, .tabs button.on { border-color: var(--decision); color: var(--decision); }
#copy-ops { margin-left: auto; }
.ops-panel { flex: 1; overflow: auto; padding: 0.6rem 0.85rem; white-space: pre-wrap; font-family: ui-monospace, Consolas, monospace; font-size: 0.82rem; color: #d7d7dc; }
.ops-row { padding: 0.25rem 0; border-bottom: 1px solid var(--line); font-family: inherit; }
.muted { color: var(--muted); }
.flags { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.3rem 0 0.5rem; }
.flags button.on { border-color: var(--ok); color: var(--ok); }
.tree-dir { list-style: none; margin: 0; padding-left: 0.85rem; }
.tree-dir > summary { cursor: pointer; color: var(--muted); padding: 0.15rem 0; }
.tree-file { padding-left: 0.2rem; }
@media (max-width: 900px) {
  body { grid-template: "bar" auto "home" 1fr "ops" minmax(8rem, 34%) / 1fr; }
  #tree, #inspect { display: none; }
}
"""

UI_APP_JS = """function headers() {
  var h = {};
  if (window.__AG2C_TOKEN) h["X-AG2C-Token"] = window.__AG2C_TOKEN;
  return h;
}
function jsonHeaders() {
  return Object.assign({ "Content-Type": "application/json" }, headers());
}
function projectBody() {
  return window.__AG2C_PROJECT ? { path: window.__AG2C_PROJECT } : {};
}
function fillList(id, rows, emptyText) {
  var section = document.getElementById(id);
  if (!section) return;
  var ul = section.querySelector("ul");
  var empty = section.querySelector(".empty");
  if (!ul) return;
  ul.innerHTML = "";
  (rows || []).forEach(function (row) {
    var li = document.createElement("li");
    li.className = row.severity || "";
    li.textContent = row.text || "";
    ul.appendChild(li);
  });
  var vacant = !ul.childElementCount;
  section.classList.add("is-ready");
  section.classList.toggle("is-empty", vacant);
  if (empty && emptyText) empty.textContent = emptyText;
}
function recordRows(records) {
  var rows = [];
  ((records && records.health) || []).forEach(function (item) {
    rows.push({ severity: "ok", text: (item.label || "") + "：" + String(item.value) });
  });
  ["patrol", "hazards", "token"].forEach(function (key) {
    ((records && records[key]) || []).forEach(function (row) { rows.push(row); });
  });
  return rows;
}
function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text || "");
    return;
  }
  window.__AG2C_COPIED = text || "";
}
function zoneCopy(kind) {
  var model = window.__AG2C_DASHBOARD || {};
  var rows = kind === "alerts" ? model.alerts : model.actions;
  var lines = (rows || []).map(function (row) { return row.text; }).filter(Boolean);
  var label = kind === "alerts" ? "系统警情" : "需要你处理";
  var header = "看板 · " + label + "：请逐条处理。";
  copyText(lines.length ? header + "\\n" + lines.map(function (line, i) { return (i + 1) + ". " + line; }).join("\\n") : header + "当前没有条目。");
}
window.ag2cFetchStatus = function () {
  var node = document.getElementById("status");
  fetch("/api/status", { headers: headers(), credentials: "omit" })
    .then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    })
    .then(function (body) {
      window.__AG2C_STATUS = body;
      window.__AG2C_STATUS_JSON = JSON.stringify(body);
      if (node) node.textContent = body.status || "";
    })
    .catch(function (err) {
      window.__AG2C_STATUS_ERROR = String(err);
      if (node) node.textContent = "error";
    });
};
function fillProjects(projects, selected) {
  var select = document.getElementById("project");
  if (!select) return;
  select.innerHTML = "";
  if (!projects.length) {
    var opt = document.createElement("option");
    opt.textContent = "还没有纳管项目";
    opt.value = "";
    select.appendChild(opt);
    return;
  }
  projects.forEach(function (item) {
    var opt = document.createElement("option");
    opt.value = item.root || "";
    opt.textContent = item.name || item.root || "";
    if (opt.value === selected) opt.selected = true;
    select.appendChild(opt);
  });
}
window.ag2cFetchDashboard = function () {
  var attention = document.getElementById("attention");
  var gate = document.getElementById("gate");
  fetch("/api/projects", { headers: headers(), credentials: "omit" })
    .then(function (res) { return res.ok ? res.json() : { projects: [] }; })
    .then(function (listing) {
      var projects = listing.projects || [];
      var body = {};
      var current = window.__AG2C_PROJECT || "";
      if (!current && projects.length && projects[0].root) current = projects[0].root;
      if (current) {
        body.path = current;
        window.__AG2C_PROJECT = current;
      }
      fillProjects(projects, current);
      var chosen = projects.filter(function (item) { return item.root === current; })[0];
      if (gate) {
        gate.textContent = chosen && chosen.delivery_enforced === false ? "门禁未开" : (chosen ? "门禁开" : "");
        gate.className = "gate" + (chosen && chosen.delivery_enforced === false ? " warn" : "");
      }
      return fetch("/api/project/dashboard", {
        method: "POST",
        headers: jsonHeaders(),
        credentials: "omit",
        body: JSON.stringify(body)
      });
    })
    .then(function (res) {
      if (!res.ok) throw new Error(String(res.status));
      return res.json();
    })
    .then(function (model) {
      window.__AG2C_DASHBOARD = model;
      if (attention) attention.textContent = (model.attention && model.attention.text) || "";
      fillCustody(model);
      fillList("action", model.actions, "没有要你处理的事");
      fillList("alert", model.alerts, "没有系统警情");
      fillList("record", recordRows(model.records), "暂无记录");
      if (typeof window.ag2cFetchTree === "function") window.ag2cFetchTree();
      if (typeof window.ag2cFetchOps === "function") window.ag2cFetchOps(window.__AG2C_OPS_TAB || "audit");
    })
    .catch(function (err) {
      window.__AG2C_DASHBOARD_ERROR = String(err);
      if (attention) attention.textContent = "连不上本地服务";
      fillList("action", [], "加载失败");
      fillList("alert", [], "加载失败");
      fillList("record", [], "加载失败");
      var custody = document.getElementById("custody");
      if (custody) {
        custody.classList.add("is-ready");
        custody.classList.add("is-empty");
      }
    });
};
function fillInspect(model) {
  var title = document.getElementById("inspect-title");
  var fields = document.getElementById("inspect-fields");
  if (title) title.textContent = (model && model.title) || "点文件树或知识卡";
  if (!fields) return;
  fields.innerHTML = "";
  var claim = (model && (model.claim || model.who)) || "";
  var labels = [
    ["path", "路径", model && model.path],
    ["claim", "归属", claim],
    ["floors", "楼层", model && model.floors],
    ["when", "最近改动", model && model.when],
    ["status", "状态", model && model.status],
    ["message", "说明", model && model.message],
    ["summary", "设计思路", model && model.summary]
  ];
  labels.forEach(function (row) {
    if (!row[2]) return;
    var dt = document.createElement("dt");
    dt.textContent = row[1];
    var dd = document.createElement("dd");
    dd.textContent = row[2];
    fields.appendChild(dt);
    fields.appendChild(dd);
  });
  window.__AG2C_INSPECT = model;
}
function nestFiles(files) {
  var root = { name: "", children: {}, files: [] };
  (files || []).forEach(function (item) {
    var parts = String(item.path || "").replace(/\\\\/g, "/").split("/").filter(Boolean);
    if (!parts.length) return;
    var node = root;
    parts.slice(0, -1).forEach(function (part) {
      if (!node.children[part]) node.children[part] = { name: part, children: {}, files: [] };
      node = node.children[part];
    });
    node.files.push(item);
  });
  return root;
}
function clickFile(item, li) {
  document.querySelectorAll("#tree li").forEach(function (node) { node.classList.remove("active"); });
  if (li) li.classList.add("active");
  fetch("/api/project/inspect", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "omit",
    body: JSON.stringify(Object.assign(projectBody(), { file: item.path }))
  })
    .then(function (res) { return res.ok ? res.json() : {}; })
    .then(fillInspect);
}
function renderTreeNode(host, node, filter) {
  Object.keys(node.children).sort().forEach(function (name) {
    var child = node.children[name];
    var details = document.createElement("details");
    details.className = "tree-dir";
    details.open = Boolean(filter);
    var summary = document.createElement("summary");
    summary.textContent = name;
    details.appendChild(summary);
    var inner = document.createElement("div");
    renderTreeNode(inner, child, filter);
    details.appendChild(inner);
    host.appendChild(details);
  });
  node.files.forEach(function (item) {
    var label = item.title || item.path || "";
    if (filter && label.toLowerCase().indexOf(filter) < 0 && String(item.path || "").toLowerCase().indexOf(filter) < 0) return;
    var li = document.createElement("li");
    li.className = "tree-file";
    li.textContent = label.split("/").pop();
    li.setAttribute("data-path", item.path || "");
    li.onclick = function () { clickFile(item, li); };
    host.appendChild(li);
  });
}
function fillCustody(model) {
  var section = document.getElementById("custody");
  if (!section) return;
  var custody = (model && model.custody) || {};
  var head = document.getElementById("custody-head");
  var irrev = document.getElementById("custody-irreversible");
  var flags = document.getElementById("custody-flags");
  var veto = document.getElementById("custody-veto");
  if (head) head.textContent = custody.headline || "";
  if (irrev) irrev.textContent = custody.irreversible || "";
  if (flags) {
    flags.innerHTML = "";
    [["看", null], ["否", false], ["授", true]].forEach(function (pair) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = pair[0];
      if (pair[1] === true && custody.granted) btn.className = "on";
      if (pair[1] === false && !custody.granted) btn.className = "on";
      if (pair[1] === null) btn.className = "on";
      if (pair[1] !== null) {
        btn.onclick = function () {
          (custody.flags || []).forEach(function (flag) {
            fetch("/api/project/proxy", {
              method: "POST",
              headers: jsonHeaders(),
              credentials: "omit",
              body: JSON.stringify({ path: window.__AG2C_PROJECT, flag: flag.id, on: pair[1] })
            }).then(function () { window.ag2cFetchDashboard(); });
          });
        };
      }
      flags.appendChild(btn);
    });
  }
  if (veto) {
    veto.innerHTML = "";
    (custody.veto || []).forEach(function (row) {
      var li = document.createElement("li");
      li.textContent = row.text || "";
      veto.appendChild(li);
    });
  }
  section.classList.add("is-ready");
  section.classList.toggle("is-empty", !window.__AG2C_PROJECT);
}
window.ag2cFetchTree = function () {
  var filter = ((document.getElementById("tree-filter") || {}).value || "").toLowerCase();
  fetch("/api/project/tree", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "omit",
    body: JSON.stringify(projectBody())
  })
    .then(function (res) { return res.ok ? res.json() : { files: [], inspect: {} }; })
    .then(function (payload) {
      var ul = document.querySelector("#tree ul");
      if (!ul) return;
      ul.innerHTML = "";
      renderTreeNode(ul, nestFiles(payload.files || []), filter);
      fillInspect(payload.inspect);
    });
};
function renderOps(payload) {
  var body = document.getElementById("ops-body");
  if (!body) return;
  body.innerHTML = "";
  function add(text) {
    var row = document.createElement("div");
    row.className = "ops-row";
    row.textContent = text;
    body.appendChild(row);
  }
  if (payload.tab === "audit") {
    var lines = payload.lines || [];
    if (!lines.length) add("还没有操作。");
    else lines.slice().reverse().forEach(add);
    window.__AG2C_OPS_TEXT = lines.slice().reverse().join("\\n") || "还没有操作。";
    return;
  }
  if (payload.tab === "gate") {
    add(payload.status ? "MCP：" + payload.status : "MCP");
    add(payload.prompt || "");
    window.__AG2C_OPS_TEXT = payload.prompt || "";
    return;
  }
  if (payload.tab === "records") {
    add("完成任务：" + String(payload.completed_tasks || 0));
    (payload.journal || []).slice(0, 30).forEach(function (item) {
      add((item.kind || item.type || "记录") + "  " + (item.summary || item.goal || item.id || JSON.stringify(item)));
    });
    if (!body.childElementCount) add("还没有实际记录。");
    window.__AG2C_OPS_TEXT = body.innerText;
    return;
  }
  if (payload.tab === "worktrees") {
    add("进行中：" + String(payload.open_tasks || 0));
    (payload.worktrees || []).forEach(function (item) {
      var life = (item.worktree && item.worktree.lifecycle) || item.state || "";
      add((item.id || "") + "  " + life + "  " + (item.goal || ""));
    });
    if ((payload.worktrees || []).length === 0) add("没有进行中的施工");
    window.__AG2C_OPS_TEXT = body.innerText;
  }
}
window.ag2cFetchOps = function (tab) {
  window.__AG2C_OPS_TAB = tab || "audit";
  document.querySelectorAll("#ops button[data-tab]").forEach(function (btn) {
    btn.classList.toggle("on", btn.getAttribute("data-tab") === window.__AG2C_OPS_TAB);
  });
  fetch("/api/project/ops", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "omit",
    body: JSON.stringify(Object.assign(projectBody(), { tab: window.__AG2C_OPS_TAB }))
  })
    .then(function (res) { return res.ok ? res.json() : {}; })
    .then(function (payload) {
      window.__AG2C_OPS = payload;
      renderOps(payload);
    });
};
window.ag2cPollDigest = function () {
  if (!window.__AG2C_PROJECT) return;
  fetch("/api/project/digest", {
    method: "POST",
    headers: jsonHeaders(),
    credentials: "omit",
    body: JSON.stringify({ path: window.__AG2C_PROJECT, previous: window.__AG2C_DIGEST || "" })
  })
    .then(function (res) { return res.ok ? res.json() : {}; })
    .then(function (payload) {
      var digest = payload.digest || "";
      if (payload.reload) {
        window.ag2cFetchDashboard();
        window.ag2cFetchTree();
      }
      if (digest) window.__AG2C_DIGEST = digest;
    });
};
document.querySelectorAll("#ops button[data-tab]").forEach(function (btn) {
  btn.onclick = function () { window.ag2cFetchOps(btn.getAttribute("data-tab")); };
});
var copyOps = document.getElementById("copy-ops");
if (copyOps) copyOps.onclick = function () { copyText(window.__AG2C_OPS_TEXT || ""); };
document.querySelectorAll("button[data-copy]").forEach(function (btn) {
  btn.onclick = function () { zoneCopy(btn.getAttribute("data-copy")); };
});
var projectSelect = document.getElementById("project");
if (projectSelect) {
  projectSelect.onchange = function () {
    window.__AG2C_PROJECT = projectSelect.value || "";
    window.__AG2C_DIGEST = "";
    window.ag2cFetchDashboard();
  };
}
var refresh = document.getElementById("refresh");
if (refresh) refresh.onclick = function () { window.ag2cFetchDashboard(); };
var addProject = document.getElementById("add-project");
if (addProject) {
  addProject.onclick = function () {
    function enroll(path) {
      if (!path) return;
      fetch("/api/projects/add", {
        method: "POST",
        headers: jsonHeaders(),
        credentials: "omit",
        body: JSON.stringify({ path: path })
      }).then(function (res) { return res.ok ? res.json() : {}; })
        .then(function (payload) {
          var added = payload.project || {};
          if (added.root) window.__AG2C_PROJECT = added.root;
          window.ag2cFetchDashboard();
        });
    }
    if (window.pywebview && window.pywebview.api && window.pywebview.api.pick_folder) {
      Promise.resolve(window.pywebview.api.pick_folder()).then(enroll);
      return;
    }
  };
}
var treeFilter = document.getElementById("tree-filter");
if (treeFilter) treeFilter.oninput = function () { window.ag2cFetchTree(); };
window.ag2cBoot = function () {
  function failBoot() {
    var attention = document.getElementById("attention");
    if (attention) attention.textContent = "连不上本地服务";
    fillList("action", [], "加载失败");
    fillList("alert", [], "加载失败");
    fillList("record", [], "加载失败");
    var custody = document.getElementById("custody");
    if (custody) {
      custody.classList.add("is-ready");
      custody.classList.add("is-empty");
    }
  }
  function start() {
    if (window.__AG2C_BOOTED || !window.__AG2C_TOKEN) return;
    window.__AG2C_BOOTED = true;
    window.ag2cFetchStatus();
    window.ag2cFetchDashboard();
    if (!window.__AG2C_DIGEST_TIMER) {
      window.__AG2C_DIGEST_TIMER = setInterval(function () { window.ag2cPollDigest(); }, 5000);
    }
  }
  if (window.__AG2C_TOKEN) {
    start();
    return;
  }
  if (window.pywebview && window.pywebview.api && window.pywebview.api.session_token) {
    Promise.resolve(window.pywebview.api.session_token()).then(function (token) {
      if (token) window.__AG2C_TOKEN = token;
      start();
    });
    return;
  }
  window.__AG2C_BOOT_TRIES = (window.__AG2C_BOOT_TRIES || 0) + 1;
  if (window.__AG2C_BOOT_TRIES > 40) {
    failBoot();
    return;
  }
  setTimeout(window.ag2cBoot, 150);
};
window.ag2cBoot();
"""
