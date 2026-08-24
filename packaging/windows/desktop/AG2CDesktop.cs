// AutoGovern2Code desktop host, adapted from CartridgeFlow Runtime Shell.
// WinForms + WebBrowser + NotifyIcon, with no external desktop runtime DLLs.

using System;
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
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("AutoGovern2Code")]
[assembly: AssemblyProduct("AutoGovern2Code")]
[assembly: AssemblyCompany("AutoGovern2Code contributors")]
[assembly: AssemblyDescription("Zero-touch governance for AI coding changes")]
[assembly: AssemblyVersion("0.7.0.0")]
[assembly: AssemblyFileVersion("0.7.0.0")]
[assembly: AssemblyInformationalVersion("0.7.0")]

namespace AutoGovern2CodeDesktop
{
    internal static class BrowserControl
    {
        public static void Configure()
        {
            try
            {
                string executable = Path.GetFileName(Process.GetCurrentProcess().MainModule.FileName);
                using (RegistryKey key = Registry.CurrentUser.CreateSubKey(
                    @"Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION"))
                {
                    if (key != null) key.SetValue(executable, 11001, RegistryValueKind.DWord);
                }
            }
            catch { }
        }
    }

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

    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            bool ownsInstance;
            using (var instance = new Mutex(true, @"Local\AutoGovern2Code.Desktop", out ownsInstance))
            {
                if (!ownsInstance)
                {
                    SingleInstance.NotifyExistingWindow();
                    return 0;
                }
                BrowserControl.Configure();
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                using (var form = new MainForm(args)) Application.Run(form);
                return 0;
            }
        }
    }

    internal sealed class MainForm : Form
    {
        private const string StartupKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValue = "AutoGovern2Code";
        private readonly WebBrowser _browser;
        private readonly Panel _loading;
        private readonly Label _loadingText;
        private readonly HttpClient _http;
        private readonly string _token;
        private readonly string _runtime;
        private NotifyIcon _tray;
        private ToolStripMenuItem _startupItem;
        private Process _server;
        private string _baseUrl;
        private bool _reallyExit;

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr handle);

        public MainForm(string[] args)
        {
            Text = "AutoGovern2Code";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(780, 520);
            ClientSize = new Size(1060, 700);
            BackColor = Color.FromArgb(245, 246, 246);
            Icon = MakeIcon();
            _token = CreateSessionToken();
            _runtime = ResolveRuntime(args);
            _http = new HttpClient(new HttpClientHandler { UseProxy = false });
            _http.Timeout = TimeSpan.FromSeconds(30);
            _loading = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            var mark = new Label
            {
                Text = "AG",
                Size = new Size(74, 74),
                BackColor = Color.FromArgb(32, 34, 37),
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 22f, FontStyle.Bold),
                TextAlign = ContentAlignment.MiddleCenter,
            };
            _loadingText = new Label
            {
                AutoSize = false,
                Size = new Size(420, 52),
                Text = "\u6b63\u5728\u68c0\u67e5\u6cbb\u7406\u9879\u76ee...",
                ForeColor = Color.FromArgb(82, 87, 90),
                Font = new Font("Microsoft YaHei UI", 11f),
                TextAlign = ContentAlignment.MiddleCenter,
            };
            _loading.Controls.Add(mark);
            _loading.Controls.Add(_loadingText);
            _loading.Resize += delegate
            {
                mark.Location = new Point((_loading.ClientSize.Width - mark.Width) / 2, Math.Max(40, (_loading.ClientSize.Height - 150) / 2));
                _loadingText.Location = new Point((_loading.ClientSize.Width - _loadingText.Width) / 2, mark.Bottom + 18);
            };
            _browser = new WebBrowser
            {
                Dock = DockStyle.Fill,
                ScriptErrorsSuppressed = true,
                IsWebBrowserContextMenuEnabled = false,
                WebBrowserShortcutsEnabled = true,
                Visible = false,
            };
            _browser.Navigating += OnBrowserNavigating;
            _browser.DocumentCompleted += delegate
            {
                _loading.Visible = false;
                _browser.Visible = true;
                _browser.BringToFront();
            };
            Controls.Add(_browser);
            Controls.Add(_loading);
            SetupTray();
            FormClosing += OnFormClosing;
            Shown += async delegate { await StartDesktopAsync(); };
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
                Fail("\u627e\u4e0d\u5230 AG2C \u6cbb\u7406\u6838\u5fc3\uff1a" + _runtime);
                return;
            }
            int port = FreePort();
            _baseUrl = "http://127.0.0.1:" + port + "/";
            var start = new ProcessStartInfo(
                _runtime,
                "desktop serve --port " + port + " --token \"" + _token + "\"")
            {
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden,
                UseShellExecute = false,
                WorkingDirectory = Path.GetDirectoryName(_runtime),
            };
            try { _server = Process.Start(start); }
            catch (Exception error) { Fail("\u65e0\u6cd5\u542f\u52a8 AG2C \u672c\u5730\u670d\u52a1\uff1a" + error.Message); return; }
            for (int attempt = 0; attempt < 100; attempt++)
            {
                await Task.Delay(100);
                if (_server != null && _server.HasExited)
                {
                    Fail("AG2C \u672c\u5730\u670d\u52a1\u672a\u80fd\u542f\u52a8\u3002");
                    return;
                }
                if (await ServerReadyAsync())
                {
                    _browser.Navigate(_baseUrl + "?bootstrap=" + Uri.EscapeDataString(_token));
                    return;
                }
            }
            Fail("AG2C \u672c\u5730\u670d\u52a1\u542f\u52a8\u8d85\u65f6\u3002");
        }

        private async Task<bool> ServerReadyAsync()
        {
            try
            {
                using (var cancellation = new CancellationTokenSource(250))
                using (var response = await _http.GetAsync(_baseUrl + "api/status", cancellation.Token))
                    return response.IsSuccessStatusCode;
            }
            catch { return false; }
        }

        private void Fail(string message)
        {
            _loadingText.Text = message;
            MessageBox.Show(this, message, "AutoGovern2Code", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        }

        private void OnBrowserNavigating(object sender, WebBrowserNavigatingEventArgs e)
        {
            if (!String.Equals(e.Url.Scheme, "ag2c", StringComparison.OrdinalIgnoreCase)) return;
            e.Cancel = true;
            if (String.Equals(e.Url.Host, "choose-project", StringComparison.OrdinalIgnoreCase))
            {
                ChooseProject();
                return;
            }
            if (String.Equals(e.Url.Host, "open-folder", StringComparison.OrdinalIgnoreCase))
            {
                string path = QueryValue(e.Url.Query, "path");
                if (Directory.Exists(path))
                {
                    try { Process.Start(new ProcessStartInfo("explorer.exe", "\"" + path + "\"") { UseShellExecute = true }); }
                    catch { }
                }
            }
        }

        private static string QueryValue(string query, string name)
        {
            foreach (string pair in query.TrimStart('?').Split('&'))
            {
                string[] parts = pair.Split(new[] { '=' }, 2);
                if (Uri.UnescapeDataString(parts[0]) == name)
                    return Uri.UnescapeDataString(parts.Length > 1 ? parts[1].Replace("+", " ") : "");
            }
            return "";
        }

        private void ChooseProject()
        {
            using (var dialog = new FolderBrowserDialog())
            {
                dialog.Description = "\u9009\u62e9\u8981\u7eb3\u5165 AutoGovern2Code \u6cbb\u7406\u7684 Git \u9879\u76ee";
                dialog.ShowNewFolderButton = false;
                if (dialog.ShowDialog(this) != DialogResult.OK) return;
                try
                {
                    if (_browser.Document != null)
                        _browser.Document.InvokeScript("ag2cProjectSelected", new object[] { dialog.SelectedPath });
                }
                catch { }
                ShowWindow();
            }
        }

        private void SetupTray()
        {
            _tray = new NotifyIcon { Icon = MakeIcon(), Text = "AutoGovern2Code", Visible = true };
            var menu = new ContextMenuStrip();
            menu.Items.Add("\u6253\u5f00 AutoGovern2Code", null, delegate { ShowWindow(); });
            menu.Items.Add("\u6dfb\u52a0\u9879\u76ee...", null, delegate { ChooseProject(); });
            menu.Items.Add("\u68c0\u67e5\u6240\u6709\u9879\u76ee", null, delegate { RefreshWebUi(); ShowWindow(); });
            menu.Items.Add(new ToolStripSeparator());
            _startupItem = new ToolStripMenuItem("\u767b\u5f55 Windows \u540e\u542f\u52a8") { Checked = StartupEnabled(), CheckOnClick = true };
            _startupItem.CheckedChanged += delegate { ApplyStartup(_startupItem.Checked); };
            menu.Items.Add(_startupItem);
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("\u9000\u51fa\u7ba1\u7406\u754c\u9762", null, delegate { _reallyExit = true; Close(); });
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

        private void RefreshWebUi()
        {
            try { if (_browser.Document != null) _browser.Document.InvokeScript("refreshStatus"); }
            catch { }
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

        private static Icon MakeIcon()
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
