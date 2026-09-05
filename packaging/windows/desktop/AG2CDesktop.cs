// AutoGovern2Code desktop host: native WinForms + NotifyIcon.
// Project list, file tree, and knowledge cards are WinForms controls.
// The Python runtime still serves the local API; this host does not embed a browser.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("AutoGovern2Code")]
[assembly: AssemblyProduct("AutoGovern2Code")]
[assembly: AssemblyCompany("AutoGovern2Code contributors")]
[assembly: AssemblyDescription("Zero-touch governance for AI coding changes")]
[assembly: AssemblyVersion("0.8.4.0")]
[assembly: AssemblyFileVersion("0.8.4.0")]
[assembly: AssemblyInformationalVersion("0.8.4")]

namespace AutoGovern2CodeDesktop
{
    internal static class SingleInstance
    {
        private const int HWND_BROADCAST = 0xffff;
        public static readonly int ActivateMessage = (int)RegisterWindowMessage("AutoGovern2Code.Desktop.Activate.v1");

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern uint RegisterWindowMessage(string message);

        [DllImport("user32.dll", SetLastError = true)]
        private static extern bool PostMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        public static void NotifyExistingWindow()
        {
            for (int attempt = 0; attempt < 8; attempt++)
            {
                PostMessage((IntPtr)HWND_BROADCAST, ActivateMessage, IntPtr.Zero, IntPtr.Zero);
                Thread.Sleep(100);
            }
        }
    }

    internal static class AppRegistration
    {
        private const string AppKey = @"Software\AutoGovern2Code";
        private const string AppPathsKey = @"Software\Microsoft\Windows\CurrentVersion\App Paths\AutoGovern2Code.exe";
        private const string UninstallKey = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\AutoGovern2Code";
        private const string StartupKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValue = "AutoGovern2Code";

        public static string ExecutablePath()
        {
            return Assembly.GetExecutingAssembly().Location;
        }

        public static string IconPath()
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "AutoGovern2Code",
                "app",
                "AutoGovern2Code.ico");
        }

        public static string StartMenuShortcutPath()
        {
            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs),
                "AutoGovern2Code.lnk");
        }

        public static void Ensure()
        {
            string exe = ExecutablePath();
            string icon = WriteIcon();
            WriteStartMenuShortcut(exe, icon);
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(AppKey))
                {
                    if (key != null)
                    {
                        key.SetValue("InstallPath", Path.GetDirectoryName(exe));
                        key.SetValue("DisplayIcon", icon);
                        key.SetValue("Version", "0.8.4");
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(AppPathsKey))
                {
                    if (key != null)
                    {
                        key.SetValue("", exe);
                        key.SetValue("Path", Path.GetDirectoryName(exe));
                    }
                }
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallKey))
                {
                    if (key != null)
                    {
                        key.SetValue("DisplayName", "AutoGovern2Code");
                        key.SetValue("DisplayIcon", icon);
                        key.SetValue("DisplayVersion", "0.8.4");
                        key.SetValue("Publisher", "AutoGovern2Code contributors");
                        key.SetValue("InstallLocation", Path.GetDirectoryName(exe));
                        key.SetValue("UninstallString", "\"" + exe + "\" --unregister");
                        key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                        key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                    }
                }
            }
            catch { }
        }

        public static void Remove()
        {
            try { File.Delete(StartMenuShortcutPath()); } catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(AppPathsKey, false); } catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(UninstallKey, false); } catch { }
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(StartupKey, true))
                    if (key != null) key.DeleteValue(StartupValue, false);
            }
            catch { }
            try { Registry.CurrentUser.DeleteSubKeyTree(AppKey, false); } catch { }
        }

        public static bool TrayHintShown()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(AppKey))
                    return key != null && Convert.ToInt32(key.GetValue("TrayHintShown", 0)) != 0;
            }
            catch { return false; }
        }

        public static void MarkTrayHintShown()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(AppKey))
                    if (key != null) key.SetValue("TrayHintShown", 1, RegistryValueKind.DWord);
            }
            catch { }
        }

        private static string WriteIcon()
        {
            string path = IconPath();
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            using (Icon icon = MainForm.CreateAppIcon())
            using (FileStream stream = File.Create(path))
                icon.Save(stream);
            return path;
        }

        private static void WriteStartMenuShortcut(string exe, string icon)
        {
            try
            {
                Type shellType = Type.GetTypeFromProgID("WScript.Shell");
                if (shellType == null) return;
                object shell = Activator.CreateInstance(shellType);
                object shortcut = shellType.InvokeMember(
                    "CreateShortcut",
                    BindingFlags.InvokeMethod,
                    null,
                    shell,
                    new object[] { StartMenuShortcutPath() });
                Type shortcutType = shortcut.GetType();
                shortcutType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, shortcut, new object[] { exe });
                shortcutType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, shortcut, new object[] { Path.GetDirectoryName(exe) });
                shortcutType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, shortcut, new object[] { icon });
                shortcutType.InvokeMember("Description", BindingFlags.SetProperty, null, shortcut, new object[] { "AutoGovern2Code" });
                shortcutType.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
            }
            catch { }
        }
    }

    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            foreach (string arg in args)
            {
                if (String.Equals(arg, "--unregister", StringComparison.OrdinalIgnoreCase))
                {
                    AppRegistration.Remove();
                    return 0;
                }
            }
            AppRegistration.Ensure();
            bool ownsInstance;
            using (var instance = new Mutex(true, @"Local\AutoGovern2Code.Desktop", out ownsInstance))
            {
                if (!ownsInstance)
                {
                    SingleInstance.NotifyExistingWindow();
                    return 0;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (var form = new MainForm(args)) Application.Run(form);
                return 0;
            }
        }
    }

    internal sealed class NamedItem
    {
        public string Title { get; set; }
        public string Id { get; set; }
        public string Kind { get; set; }
        public Dictionary<string, object> Data { get; set; }
        public override string ToString() { return Title ?? Id ?? ""; }
    }

    internal sealed class MainForm : Form
    {
        private const string StartupKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValue = "AutoGovern2Code";
        private readonly HttpClient _http;
        private readonly string _token;
        private readonly string _runtime;
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        private readonly Panel _loading;
        private readonly Label _loadingText;
        private readonly Label _status;
        private readonly ListBox _projects;
        private readonly Label _detailName;
        private readonly Label _detailPath;
        private readonly Label _detailHealth;
        private readonly Label _issues;
        private readonly TextBox _search;
        private readonly ComboBox _filter;
        private readonly TreeView _tree;
        private readonly ListBox _cards;
        private readonly TextBox _inspector;
        private readonly Button _openFolder;
        private readonly Button _check;
        private readonly Button _stop;
        private readonly Button _resume;
        private readonly Button _uninstall;
        private NotifyIcon _tray;
        private ToolStripMenuItem _startupItem;
        private Process _server;
        private string _baseUrl;
        private bool _reallyExit;
        private bool _busy;
        private Dictionary<string, object> _details;

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr handle);

        public MainForm(string[] args)
        {
            Text = "AutoGovern2Code";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(960, 640);
            ClientSize = new Size(1280, 860);
            BackColor = Color.FromArgb(245, 246, 246);
            Font = new Font("Microsoft YaHei UI", 9f);
            Icon = CreateAppIcon();
            _token = CreateSessionToken();
            _runtime = ResolveRuntime(args);
            _http = new HttpClient(new HttpClientHandler { UseProxy = false });
            _http.Timeout = TimeSpan.FromSeconds(60);

            var header = new Panel { Dock = DockStyle.Top, Height = 56, BackColor = Color.White };
            var mark = new Label { Text = "AG", Size = new Size(40, 40), Location = new Point(16, 8), BackColor = Color.FromArgb(32, 34, 37), ForeColor = Color.White, Font = new Font("Segoe UI", 12f, FontStyle.Bold), TextAlign = ContentAlignment.MiddleCenter };
            var title = new Label { Text = "AutoGovern2Code", AutoSize = true, Location = new Point(64, 16), Font = new Font("Microsoft YaHei UI", 12f, FontStyle.Bold) };
            _status = new Label { AutoSize = true, Location = new Point(250, 20), ForeColor = Color.FromArgb(82, 87, 90), Text = "正在检查项目" };
            var refresh = MakeButton("刷新", false);
            refresh.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            var add = MakeButton("添加项目", true);
            add.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            header.Resize += delegate
            {
                add.Location = new Point(header.ClientSize.Width - add.Width - 16, 12);
                refresh.Location = new Point(add.Left - refresh.Width - 8, 12);
            };
            refresh.Click += async delegate { await RefreshProjectsAsync(); };
            add.Click += async delegate { await ChooseProjectAsync(); };
            header.Controls.Add(mark);
            header.Controls.Add(title);
            header.Controls.Add(_status);
            header.Controls.Add(refresh);
            header.Controls.Add(add);

            var split = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 260, Panel1MinSize = 180 };
            _projects = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false, DisplayMember = "Title" };
            _projects.SelectedIndexChanged += async delegate { await LoadSelectedAsync(); };
            split.Panel1.Controls.Add(_projects);

            var detail = new Panel { Dock = DockStyle.Fill };
            _detailName = new Label { AutoSize = false, Height = 28, Dock = DockStyle.Top, Font = new Font("Microsoft YaHei UI", 14f, FontStyle.Bold), Padding = new Padding(12, 8, 12, 0), Text = "选择一个项目" };
            _detailPath = new Label { AutoSize = false, Height = 22, Dock = DockStyle.Top, ForeColor = Color.FromArgb(90, 90, 90), Padding = new Padding(12, 0, 12, 0) };
            _detailHealth = new Label { AutoSize = false, Height = 22, Dock = DockStyle.Top, Padding = new Padding(12, 0, 12, 0), Text = "尚未加载" };
            _issues = new Label { AutoSize = false, Height = 40, Dock = DockStyle.Top, ForeColor = Color.FromArgb(153, 27, 27), Padding = new Padding(12, 4, 12, 0) };
            var actions = new FlowLayoutPanel { Dock = DockStyle.Top, Height = 40, Padding = new Padding(8, 4, 8, 4), WrapContents = false };
            _openFolder = MakeButton("打开文件夹", false);
            _check = MakeButton("重新检查", false);
            _stop = MakeButton("停止治理", false);
            _resume = MakeButton("恢复治理", false);
            _uninstall = MakeButton("卸载项目", false);
            _openFolder.Click += delegate { OpenSelectedFolder(); };
            _check.Click += async delegate { await PostProjectAsync("/api/projects/check"); };
            _stop.Click += async delegate { await ConfirmPostAsync("停止治理后，这个仓库不再被 AG2C 拦截提交。证据还在。", "/api/projects/remove"); };
            _resume.Click += async delegate { await PostProjectAsync("/api/projects/resume"); };
            _uninstall.Click += async delegate { await ConfirmPostAsync("卸载项目会删除这份治理档案，不能恢复。仓库源码不会被删。", "/api/projects/uninstall"); };
            actions.Controls.AddRange(new Control[] { _openFolder, _check, _stop, _resume, _uninstall });
            var tools = new Panel { Dock = DockStyle.Top, Height = 36, Padding = new Padding(12, 4, 12, 4) };
            _search = new TextBox { Width = 240, Location = new Point(12, 6) };
            _search.TextChanged += delegate { RenderCoverage(); };
            _filter = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 140, Location = new Point(260, 6) };
            foreach (string item in new[] { "全部", "开工", "黑盒", "无主", "过期", "未普查", "重复认领", "废弃未清", "未验收", "AI正在写" })
                _filter.Items.Add(item);
            _filter.SelectedIndex = 0;
            _filter.SelectedIndexChanged += delegate { RenderCoverage(); };
            tools.Controls.Add(_search);
            tools.Controls.Add(_filter);
            var coverage = new SplitContainer { Dock = DockStyle.Fill, SplitterDistance = 420 };
            var treeHost = new Panel { Dock = DockStyle.Fill };
            var treeLabel = new Label { Text = "项目文件树", Dock = DockStyle.Top, Height = 22, Padding = new Padding(8, 4, 0, 0) };
            _tree = new TreeView { Dock = DockStyle.Fill };
            _tree.AfterSelect += delegate { InspectNode(_tree.SelectedNode); };
            treeHost.Controls.Add(_tree);
            treeHost.Controls.Add(treeLabel);
            var right = new SplitContainer { Dock = DockStyle.Fill, Orientation = Orientation.Horizontal, SplitterDistance = 220 };
            var cardHost = new Panel { Dock = DockStyle.Fill };
            var cardLabel = new Label { Text = "知识卡片", Dock = DockStyle.Top, Height = 22, Padding = new Padding(8, 4, 0, 0) };
            _cards = new ListBox { Dock = DockStyle.Fill, IntegralHeight = false };
            _cards.SelectedIndexChanged += delegate { InspectCard(_cards.SelectedItem as NamedItem); };
            cardHost.Controls.Add(_cards);
            cardHost.Controls.Add(cardLabel);
            _inspector = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, BorderStyle = BorderStyle.None, BackColor = Color.White, Padding = new Padding(8) };
            right.Panel1.Controls.Add(cardHost);
            right.Panel2.Controls.Add(_inspector);
            coverage.Panel1.Controls.Add(treeHost);
            coverage.Panel2.Controls.Add(right);

            detail.Controls.Add(coverage);
            detail.Controls.Add(tools);
            detail.Controls.Add(actions);
            detail.Controls.Add(_issues);
            detail.Controls.Add(_detailHealth);
            detail.Controls.Add(_detailPath);
            detail.Controls.Add(_detailName);
            split.Panel2.Controls.Add(detail);

            _loading = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            var loadMark = new Label { Text = "AG", Size = new Size(74, 74), BackColor = Color.FromArgb(32, 34, 37), ForeColor = Color.White, Font = new Font("Segoe UI", 22f, FontStyle.Bold), TextAlign = ContentAlignment.MiddleCenter };
            _loadingText = new Label { AutoSize = false, Size = new Size(420, 52), Text = "正在检查治理项目...", ForeColor = Color.FromArgb(82, 87, 90), Font = new Font("Microsoft YaHei UI", 11f), TextAlign = ContentAlignment.MiddleCenter };
            _loading.Controls.Add(loadMark);
            _loading.Controls.Add(_loadingText);
            _loading.Resize += delegate
            {
                loadMark.Location = new Point((_loading.ClientSize.Width - loadMark.Width) / 2, Math.Max(40, (_loading.ClientSize.Height - 150) / 2));
                _loadingText.Location = new Point((_loading.ClientSize.Width - _loadingText.Width) / 2, loadMark.Bottom + 18);
            };

            Controls.Add(split);
            Controls.Add(header);
            Controls.Add(_loading);
            _loading.BringToFront();
            SetupTray();
            FormClosing += OnFormClosing;
            Shown += async delegate { await StartDesktopAsync(); };
        }

        private static Button MakeButton(string text, bool primary)
        {
            return new Button
            {
                Text = text,
                AutoSize = true,
                Height = 32,
                Padding = new Padding(10, 4, 10, 4),
                FlatStyle = FlatStyle.Flat,
                BackColor = primary ? Color.FromArgb(32, 34, 37) : Color.White,
                ForeColor = primary ? Color.White : Color.FromArgb(32, 34, 37),
            };
        }

        protected override void WndProc(ref Message message)
        {
            if (message.Msg == SingleInstance.ActivateMessage)
            {
                ShowWindow();
                return;
            }
            base.WndProc(ref message);
        }

        private string ResolveRuntime(string[] args)
        {
            foreach (string arg in args)
                if (arg.StartsWith("--runtime=", StringComparison.OrdinalIgnoreCase))
                    return Path.GetFullPath(arg.Substring("--runtime=".Length));
            string app = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
            return Path.Combine(app, "ag2c", "ag2c.exe");
        }

        private static int FreePort()
        {
            var listener = new TcpListener(IPAddress.Loopback, 0);
            listener.Start();
            int port = ((IPEndPoint)listener.LocalEndpoint).Port;
            listener.Stop();
            return port;
        }

        private async Task StartDesktopAsync()
        {
            if (!File.Exists(_runtime))
            {
                Fail("找不到 AG2C 治理核心：" + _runtime);
                return;
            }
            int port = FreePort();
            _baseUrl = "http://127.0.0.1:" + port + "/";
            var start = new ProcessStartInfo(_runtime, "desktop serve --port " + port + " --token \"" + _token + "\"")
            {
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(_runtime),
            };
            try { _server = Process.Start(start); }
            catch (Exception error) { Fail("无法启动 AG2C 本地服务：" + error.Message); return; }
            for (int attempt = 0; attempt < 100; attempt++)
            {
                await Task.Delay(100);
                if (_server != null && _server.HasExited)
                {
                    Fail("AG2C 本地服务未能启动。");
                    return;
                }
                try
                {
                    using (var response = await _http.GetAsync(_baseUrl + "api/status"))
                    {
                        if (response.IsSuccessStatusCode)
                        {
                            _loading.Visible = false;
                            await RefreshProjectsAsync();
                            return;
                        }
                    }
                }
                catch { }
            }
            Fail("AG2C 本地服务启动超时。");
        }

        private NamedItem SelectedProject()
        {
            return _projects.SelectedItem as NamedItem;
        }

        private async Task RefreshProjectsAsync()
        {
            if (_busy) return;
            _busy = true;
            _status.Text = "正在刷新";
            try
            {
                await ApiAsync("POST", "api/projects/align", "{}");
                Dictionary<string, object> payload = await ApiAsync("GET", "api/projects", null);
                object selected = SelectedProject() != null ? SelectedProject().Id : null;
                _projects.Items.Clear();
                ArrayList list = payload != null ? payload["projects"] as ArrayList : null;
                if (list != null)
                {
                    foreach (object raw in list)
                    {
                        Dictionary<string, object> row = raw as Dictionary<string, object>;
                        if (row == null) continue;
                        NamedItem item = new NamedItem();
                        item.Id = Str(row, "root");
                        item.Title = Str(row, "name") + "  [" + Str(row, "state") + "]";
                        item.Kind = Str(row, "state");
                        item.Data = row;
                        _projects.Items.Add(item);
                        if (selected != null && item.Id == (string)selected)
                            _projects.SelectedItem = item;
                    }
                }
                _status.Text = _projects.Items.Count == 0 ? "还没有治理项目" : ("已接入 " + _projects.Items.Count + " 个项目");
                if (_projects.SelectedItem == null && _projects.Items.Count > 0)
                    _projects.SelectedIndex = 0;
            }
            catch (Exception error)
            {
                _status.Text = error.Message;
            }
            finally { _busy = false; }
        }

        private async Task LoadSelectedAsync()
        {
            NamedItem project = SelectedProject();
            if (project == null || project.Data == null)
                return;
            _detailName.Text = Str(project.Data, "name");
            _detailPath.Text = Str(project.Data, "root");
            _detailHealth.Text = HealthText(project.Data);
            _issues.Text = string.Join("；", Strings(project.Data, "issues"));
            string governance = Str(project.Data, "governance");
            _stop.Enabled = governance != "stopped";
            _resume.Enabled = governance == "stopped";
            try
            {
                _details = await ApiAsync("POST", "api/project/details", "{\"path\":" + JsonString(project.Id) + "}");
                RenderCoverage();
            }
            catch (Exception error)
            {
                _inspector.Text = error.Message;
            }
        }

        private static string HealthText(Dictionary<string, object> row)
        {
            string state = Str(row, "state");
            if (state == "protected") return "施工检查已通过";
            if (state == "stopped") return "治理已停止";
            if (state == "inactive") return "守卫未接通";
            return "需要注意";
        }

        private string FilterFlag()
        {
            string[] flags = { "", "exploring", "opaque", "unowned", "stale", "unreviewed", "ambiguous", "abandoned", "undeclared", "writing" };
            int index = _filter.SelectedIndex;
            if (index < 0 || index >= flags.Length) return "";
            return flags[index];
        }

        private void RenderCoverage()
        {
            _tree.BeginUpdate();
            _tree.Nodes.Clear();
            _cards.Items.Clear();
            if (_details == null)
            {
                _tree.EndUpdate();
                _inspector.Text = "选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。";
                return;
            }
            Dictionary<string, object> graph = _details.ContainsKey("graph") ? _details["graph"] as Dictionary<string, object> : null;
            ArrayList nodes = graph != null && graph.ContainsKey("nodes") ? graph["nodes"] as ArrayList : null;
            string query = (_search.Text ?? "").Trim().ToLowerInvariant();
            string flag = FilterFlag();
            Dictionary<string, TreeNode> folders = new Dictionary<string, TreeNode>(StringComparer.OrdinalIgnoreCase);
            if (nodes != null)
            {
                foreach (object raw in nodes)
                {
                    Dictionary<string, object> node = raw as Dictionary<string, object>;
                    if (node == null) continue;
                    string kind = Str(node, "kind");
                    if (kind == "knowledge" || kind == "gap")
                    {
                        if (!Match(node, query, flag)) continue;
                        NamedItem card = new NamedItem();
                        card.Id = Str(node, "id");
                        card.Title = Str(node, "title");
                        if (card.Title.Length == 0) card.Title = card.Id;
                        string status = FirstFlagLabel(node);
                        if (status.Length > 0) card.Title = card.Title + "  ·  " + status;
                        card.Kind = kind;
                        card.Data = node;
                        _cards.Items.Add(card);
                    }
                    if (kind != "file") continue;
                    if (!Match(node, query, flag)) continue;
                    string path = Str(node, "path");
                    if (path.IndexOf(':') >= 0) path = path.Substring(path.IndexOf(':') + 1);
                    path = path.Replace("\\", "/").Trim('/');
                    if (path.Length == 0) continue;
                    TreeNode parent = null;
                    string prefix = "";
                    string[] parts = path.Split('/');
                    for (int i = 0; i < parts.Length; i++)
                    {
                        prefix = prefix.Length == 0 ? parts[i] : prefix + "/" + parts[i];
                        TreeNode found;
                        if (!folders.TryGetValue(prefix, out found))
                        {
                            found = new TreeNode(parts[i]);
                            found.Tag = node;
                            if (parent == null) _tree.Nodes.Add(found);
                            else parent.Nodes.Add(found);
                            folders[prefix] = found;
                        }
                        parent = found;
                    }
                }
            }
            _tree.ExpandAll();
            _tree.EndUpdate();
            object headline = graph != null && graph.ContainsKey("headline") ? graph["headline"] : null;
            if (_inspector.TextLength == 0)
                _inspector.Text = headline != null ? Convert.ToString(headline) : "点文件树或知识卡查看归属。";
        }

        private static bool Match(Dictionary<string, object> node, string query, string flag)
        {
            if (flag.Length > 0 && !HasFlag(node, flag)) return false;
            if (query.Length == 0) return true;
            string blob = (Str(node, "title") + " " + Str(node, "path") + " " + Str(node, "summary") + " " + Str(node, "id")).ToLowerInvariant();
            return blob.IndexOf(query) >= 0;
        }

        private static bool HasFlag(Dictionary<string, object> node, string flag)
        {
            ArrayList flags = node.ContainsKey("flags") ? node["flags"] as ArrayList : null;
            if (flags == null) return false;
            foreach (object item in flags)
                if (Convert.ToString(item) == flag) return true;
            if (flag == "abandoned" && Str(node, "role") == "leftover") return true;
            return Str(node, "role") == flag;
        }

        private static string FirstFlagLabel(Dictionary<string, object> node)
        {
            ArrayList flags = node.ContainsKey("flags") ? node["flags"] as ArrayList : null;
            if (flags == null || flags.Count == 0) return Str(node, "statusLabel");
            string flag = Convert.ToString(flags[0]);
            if (flag == "exploring") return "开工";
            if (flag == "opaque") return "黑盒";
            if (flag == "unowned") return "无主";
            if (flag == "abandoned") return "废弃未清";
            if (flag == "stale") return "过期";
            if (flag == "unreviewed") return "未普查";
            return flag;
        }

        private void InspectNode(TreeNode node)
        {
            if (node == null) return;
            Dictionary<string, object> data = node.Tag as Dictionary<string, object>;
            if (data == null) return;
            _inspector.Text = FormatInspect(data);
        }

        private void InspectCard(NamedItem card)
        {
            if (card == null || card.Data == null) return;
            _inspector.Text = FormatInspect(card.Data);
        }

        private static string FormatInspect(Dictionary<string, object> node)
        {
            StringBuilder text = new StringBuilder();
            text.AppendLine(Str(node, "title"));
            text.AppendLine(Str(node, "path"));
            text.AppendLine();
            string summary = Str(node, "summary");
            if (summary.Length > 0) text.AppendLine(summary);
            text.AppendLine("谁管理：" + (Str(node, "coverageLabel").Length > 0 ? Str(node, "coverageLabel") : Join(node, "coveredBy")));
            text.AppendLine("角色：" + (Str(node, "roleLabel").Length > 0 ? Str(node, "roleLabel") : FirstFlagLabel(node)));
            text.AppendLine("状态：" + FirstFlagLabel(node));
            return text.ToString();
        }

        private static string Join(Dictionary<string, object> node, string key)
        {
            ArrayList values = node.ContainsKey(key) ? node[key] as ArrayList : null;
            if (values == null || values.Count == 0) return "—";
            List<string> parts = new List<string>();
            foreach (object item in values) parts.Add(Convert.ToString(item));
            return string.Join("、", parts.ToArray());
        }

        private static string Str(Dictionary<string, object> row, string key)
        {
            if (row == null || !row.ContainsKey(key) || row[key] == null) return "";
            return Convert.ToString(row[key]);
        }

        private static string[] Strings(Dictionary<string, object> row, string key)
        {
            ArrayList values = row != null && row.ContainsKey(key) ? row[key] as ArrayList : null;
            if (values == null) return new string[0];
            List<string> parts = new List<string>();
            foreach (object item in values)
            {
                string text = Convert.ToString(item);
                if (!string.IsNullOrEmpty(text)) parts.Add(text);
            }
            return parts.ToArray();
        }

        private async Task<Dictionary<string, object>> ApiAsync(string method, string path, string body)
        {
            var request = new HttpRequestMessage(new HttpMethod(method), _baseUrl + path);
            request.Headers.Add("X-AG2C-Token", _token);
            if (body != null)
                request.Content = new StringContent(body, Encoding.UTF8, "application/json");
            using (HttpResponseMessage response = await _http.SendAsync(request))
            {
                string text = await response.Content.ReadAsStringAsync();
                if (!response.IsSuccessStatusCode)
                    throw new InvalidOperationException(ExtractError(text, response.StatusCode.ToString()));
                if (string.IsNullOrWhiteSpace(text)) return new Dictionary<string, object>();
                return _json.Deserialize<Dictionary<string, object>>(text);
            }
        }

        private static string ExtractError(string text, string fallback)
        {
            try
            {
                var ser = new JavaScriptSerializer();
                Dictionary<string, object> payload = ser.Deserialize<Dictionary<string, object>>(text);
                if (payload != null && payload.ContainsKey("error"))
                    return Convert.ToString(payload["error"]);
            }
            catch { }
            return fallback;
        }

        private static string JsonString(string value)
        {
            if (value == null) return "\"\"";
            return "\"" + value.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
        }

        private async Task ChooseProjectAsync()
        {
            ShowWindow();
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "选择要纳入 AutoGovern2Code 治理的 Git 项目";
                dialog.ShowNewFolderButton = false;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                _busy = true;
                try
                {
                    await ApiAsync("POST", "api/projects/add", "{\"path\":" + JsonString(dialog.SelectedPath) + "}");
                }
                catch (Exception error)
                {
                    MessageBox.Show(this, error.Message, "AutoGovern2Code", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                finally { _busy = false; }
                await RefreshProjectsAsync();
            }
        }

        private async Task PostProjectAsync(string path)
        {
            NamedItem project = SelectedProject();
            if (project == null) return;
            _busy = true;
            try
            {
                await ApiAsync("POST", path.TrimStart('/'), "{\"path\":" + JsonString(project.Id) + "}");
            }
            catch (Exception error)
            {
                MessageBox.Show(this, error.Message, "AutoGovern2Code", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            finally { _busy = false; }
            await RefreshProjectsAsync();
        }

        private async Task ConfirmPostAsync(string message, string path)
        {
            if (MessageBox.Show(this, message, "AutoGovern2Code", MessageBoxButtons.OKCancel, MessageBoxIcon.Warning) != DialogResult.OK)
                return;
            await PostProjectAsync(path);
        }

        private void OpenSelectedFolder()
        {
            NamedItem project = SelectedProject();
            if (project == null || !Directory.Exists(project.Id)) return;
            try { Process.Start(new ProcessStartInfo("explorer.exe", "\"" + project.Id + "\"") { UseShellExecute = true }); }
            catch { }
        }

        private void Fail(string message)
        {
            _loading.Visible = true;
            _loading.BringToFront();
            _loadingText.Text = message;
            MessageBox.Show(this, message, "AutoGovern2Code", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private void SetupTray()
        {
            _tray = new NotifyIcon { Icon = CreateAppIcon(), Text = "AutoGovern2Code — 双击打开", Visible = true };
            var menu = new ContextMenuStrip();
            menu.Items.Add("打开 AutoGovern2Code", null, delegate { ShowWindow(); });
            menu.Items.Add("添加项目...", null, async delegate { await ChooseProjectAsync(); });
            menu.Items.Add("检查所有项目", null, async delegate { await RefreshProjectsAsync(); ShowWindow(); });
            menu.Items.Add(new ToolStripSeparator());
            _startupItem = new ToolStripMenuItem("登录 Windows 后启动") { Checked = StartupEnabled(), CheckOnClick = true };
            _startupItem.CheckedChanged += delegate { ApplyStartup(_startupItem.Checked); };
            menu.Items.Add(_startupItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("退出管理界面", null, delegate { _reallyExit = true; Close(); });
            _tray.ContextMenuStrip = menu;
            _tray.DoubleClick += delegate { ShowWindow(); };
        }

        private void ShowWindow()
        {
            Show();
            if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
            ShowInTaskbar = true;
            Activate();
            SetForegroundWindow(Handle);
        }

        private static bool StartupEnabled()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(StartupKey))
                    return key != null && key.GetValue(StartupValue) != null;
            }
            catch { return false; }
        }

        private static void ApplyStartup(bool enabled)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(StartupKey))
                {
                    if (enabled) key.SetValue(StartupValue, "\"" + Assembly.GetExecutingAssembly().Location + "\"");
                    else key.DeleteValue(StartupValue, false);
                }
            }
            catch { }
        }

        private void OnFormClosing(object sender, FormClosingEventArgs e)
        {
            if (!_reallyExit && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                Hide();
                ShowInTaskbar = false;
                if (_tray != null && !AppRegistration.TrayHintShown())
                {
                    _tray.ShowBalloonTip(5000, "AutoGovern2Code 还在运行", "窗口已放到右下角托盘。开始菜单搜索 AutoGovern2Code 也能再次打开。", ToolTipIcon.Info);
                    AppRegistration.MarkTrayHintShown();
                }
                return;
            }
            try
            {
                if (_server != null && !_server.HasExited)
                {
                    var request = new HttpRequestMessage(HttpMethod.Post, _baseUrl + "api/shutdown");
                    request.Headers.Add("X-AG2C-Token", _token);
                    request.Content = new StringContent("{}", Encoding.UTF8, "application/json");
                    _http.SendAsync(request).Wait(TimeSpan.FromSeconds(1));
                    if (!_server.WaitForExit(1500)) _server.Kill();
                }
            }
            catch { try { if (_server != null && !_server.HasExited) _server.Kill(); } catch { } }
            if (_tray != null) { _tray.Visible = false; _tray.Dispose(); }
        }

        protected override void Dispose(bool disposing)
        {
            if (disposing) _http.Dispose();
            base.Dispose(disposing);
        }

        internal static Icon CreateAppIcon()
        {
            using (var bitmap = new Bitmap(32, 32))
            using (var graphics = Graphics.FromImage(bitmap))
            {
                graphics.Clear(Color.FromArgb(32, 34, 37));
                using (var font = new Font("Segoe UI", 10.5f, FontStyle.Bold))
                using (var brush = new SolidBrush(Color.White))
                    graphics.DrawString("AG", font, brush, new PointF(3.2f, 7.4f));
                IntPtr handle = bitmap.GetHicon();
                try { using (Icon borrowed = Icon.FromHandle(handle)) return (Icon)borrowed.Clone(); }
                finally { DestroyIcon(handle); }
            }
        }

        private static string CreateSessionToken()
        {
            byte[] bytes = new byte[32];
            using (RandomNumberGenerator random = RandomNumberGenerator.Create()) random.GetBytes(bytes);
            return Convert.ToBase64String(bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_');
        }
    }
}
