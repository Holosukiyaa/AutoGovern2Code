// Leftover WinForms host. The installer now freezes packaging/windows/desktop/app.py
// (PySide6). Do not build this file. Remove it in a retirement task.
// AutoGovern2Code desktop host: native WinForms + NotifyIcon.
// Project cards, file tree, and knowledge cards are WinForms controls skinned
// to the previous light-console CSS. The host does not embed a browser.

using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
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
            if (!MainForm.IsPortable(args))
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

    internal static class Ui
    {
        public static readonly Color Page = Color.FromArgb(243, 244, 246);
        public static readonly Color Ink = Color.FromArgb(31, 41, 55);
        public static readonly Color Title = Color.FromArgb(17, 24, 39);
        public static readonly Color Mute = Color.FromArgb(107, 114, 128);
        public static readonly Color Line = Color.FromArgb(229, 231, 235);
        public static readonly Color Primary = Color.FromArgb(37, 99, 235);
        public static readonly Color PrimaryDeep = Color.FromArgb(29, 78, 216);
        public static readonly Color PrimarySoft = Color.FromArgb(239, 246, 255);
        public static readonly Color PrimaryHover = Color.FromArgb(219, 234, 254);
        public static readonly Color SecondaryLine = Color.FromArgb(209, 213, 219);
        public static readonly Color SecondaryText = Color.FromArgb(55, 65, 81);
        public static readonly Color CardPane = Color.FromArgb(248, 250, 249);
        public static readonly Color ActiveCard = Color.FromArgb(248, 251, 255);
        public static readonly Color HoverCard = Color.FromArgb(248, 250, 252);
        public static readonly Color IssueBg = Color.FromArgb(255, 247, 237);
        public static readonly Color IssueText = Color.FromArgb(154, 52, 18);
        public static readonly Color Protected = Color.FromArgb(22, 163, 74);
        public static readonly Color Attention = Color.FromArgb(217, 119, 6);
        public static readonly Color Danger = Color.FromArgb(220, 38, 38);
        public static readonly Color Stopped = Color.FromArgb(156, 163, 175);
        public static readonly Color DangerLine = Color.FromArgb(254, 202, 202);
        public static readonly Color DangerHover = Color.FromArgb(254, 242, 242);
        public static readonly Color ProtectSoft = Color.FromArgb(220, 252, 231);
        public static readonly Color AttentionSoft = Color.FromArgb(254, 243, 199);
        public static readonly Color DangerSoft = Color.FromArgb(254, 226, 226);
        public static readonly Color StoppedSoft = Color.FromArgb(243, 244, 246);

        public static GraphicsPath RoundRect(Rectangle bounds, int radius)
        {
            int d = Math.Max(2, radius * 2);
            if (d > bounds.Width) d = Math.Max(2, bounds.Width);
            if (d > bounds.Height) d = Math.Max(2, bounds.Height);
            GraphicsPath path = new GraphicsPath();
            if (bounds.Width <= 0 || bounds.Height <= 0)
            {
                path.AddRectangle(bounds);
                return path;
            }
            path.AddArc(bounds.X, bounds.Y, d, d, 180, 90);
            path.AddArc(bounds.Right - d, bounds.Y, d, d, 270, 90);
            path.AddArc(bounds.Right - d, bounds.Bottom - d, d, d, 0, 90);
            path.AddArc(bounds.X, bounds.Bottom - d, d, d, 90, 90);
            path.CloseFigure();
            return path;
        }

        public static void PaintRound(Graphics graphics, Rectangle bounds, int radius, Color fill, Color border)
        {
            graphics.SmoothingMode = SmoothingMode.AntiAlias;
            using (GraphicsPath path = RoundRect(bounds, radius))
            using (SolidBrush brush = new SolidBrush(fill))
            using (Pen pen = new Pen(border))
            {
                graphics.FillPath(brush, path);
                graphics.DrawPath(pen, path);
            }
        }

        public static void ApplyRound(Control control, int radius)
        {
            if (control == null || control.Width <= 0 || control.Height <= 0) return;
            using (GraphicsPath path = RoundRect(new Rectangle(0, 0, control.Width, control.Height), radius))
            {
                Region old = control.Region;
                control.Region = new Region(path);
                if (old != null) old.Dispose();
            }
        }

        public static Color StateColor(string state)
        {
            if (state == "protected") return Protected;
            if (state == "attention") return Attention;
            if (state == "inactive" || state == "missing") return Danger;
            return Stopped;
        }

        public static Color StateSoft(string state)
        {
            if (state == "protected") return ProtectSoft;
            if (state == "attention") return AttentionSoft;
            if (state == "inactive" || state == "missing") return DangerSoft;
            return StoppedSoft;
        }

        public static string StateLabel(string state)
        {
            if (state == "protected") return "治理检查已通过";
            if (state == "attention") return "需要处理";
            if (state == "missing") return "目录不可用";
            if (state == "stopped") return "治理已关闭";
            return "未生效";
        }

        public static string Glyph(string name)
        {
            if (string.IsNullOrEmpty(name)) return "AG";
            string trimmed = name.Trim();
            if (trimmed.Length == 1) return trimmed.ToUpperInvariant();
            return trimmed.Substring(0, Math.Min(2, trimmed.Length)).ToUpperInvariant();
        }
    }

    internal sealed class CardPanel : Panel
    {
        private readonly int _radius;
        private readonly Color _border;

        public CardPanel(int radius, Color fill, Color border)
        {
            _radius = radius;
            _border = border;
            BackColor = fill;
            DoubleBuffered = true;
            HandleCreated += delegate { Ui.ApplyRound(this, _radius); };
        }

        protected override void OnSizeChanged(EventArgs e)
        {
            base.OnSizeChanged(e);
            Ui.ApplyRound(this, _radius);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Rectangle box = new Rectangle(0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
            Ui.PaintRound(e.Graphics, box, _radius, BackColor, _border);
        }
    }

    internal sealed class ChromeButton : Button
    {
        private readonly string _kind;
        private bool _hover;

        public ChromeButton(string text, string kind)
        {
            _kind = kind;
            Text = text;
            AutoSize = true;
            Height = 36;
            MinimumSize = new Size(36, 36);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            FlatAppearance.MouseOverBackColor = Color.Transparent;
            FlatAppearance.MouseDownBackColor = Color.Transparent;
            Font = new Font("Microsoft YaHei UI", 9f, FontStyle.Bold);
            Cursor = Cursors.Hand;
            Padding = new Padding(14, 0, 14, 0);
            UseVisualStyleBackColor = false;
            ApplyFill();
        }

        private void ApplyFill()
        {
            if (_kind == "primary")
            {
                BackColor = _hover ? Ui.PrimaryHover : Ui.PrimarySoft;
                ForeColor = Ui.PrimaryDeep;
            }
            else if (_kind == "danger")
            {
                BackColor = _hover ? Ui.DangerHover : Color.White;
                ForeColor = Ui.Danger;
            }
            else
            {
                BackColor = _hover ? Color.FromArgb(249, 250, 251) : Color.White;
                ForeColor = _kind == "icon" ? Color.FromArgb(75, 85, 99) : Ui.SecondaryText;
            }
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            _hover = true;
            ApplyFill();
            base.OnMouseEnter(e);
            Invalidate();
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            _hover = false;
            ApplyFill();
            base.OnMouseLeave(e);
            Invalidate();
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            Ui.ApplyRound(this, 8);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Color border = Ui.SecondaryLine;
            if (_kind == "primary") border = Ui.Primary;
            if (_kind == "danger") border = Ui.DangerLine;
            Rectangle box = new Rectangle(0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
            Ui.PaintRound(e.Graphics, box, 8, BackColor, border);
            TextRenderer.DrawText(
                e.Graphics,
                Text,
                Font,
                ClientRectangle,
                ForeColor,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
        }
    }

    internal sealed class ChipButton : Button
    {
        public string Flag;
        private bool _active;
        private bool _hover;

        public ChipButton(string text, string flag)
        {
            Flag = flag;
            Text = text;
            AutoSize = true;
            Height = 30;
            MinimumSize = new Size(48, 30);
            FlatStyle = FlatStyle.Flat;
            FlatAppearance.BorderSize = 0;
            FlatAppearance.MouseOverBackColor = Color.Transparent;
            FlatAppearance.MouseDownBackColor = Color.Transparent;
            Font = new Font("Microsoft YaHei UI", 8f);
            Cursor = Cursors.Hand;
            Padding = new Padding(10, 0, 10, 0);
            UseVisualStyleBackColor = false;
            SetActive(false);
        }

        public void SetActive(bool active)
        {
            _active = active;
            if (_active)
            {
                BackColor = Ui.PrimaryDeep;
                ForeColor = Color.White;
            }
            else
            {
                BackColor = _hover ? Ui.HoverCard : Color.White;
                ForeColor = Ui.SecondaryText;
            }
            Invalidate();
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            _hover = true;
            if (!_active) BackColor = Ui.HoverCard;
            base.OnMouseEnter(e);
            Invalidate();
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            _hover = false;
            if (!_active) BackColor = Color.White;
            base.OnMouseLeave(e);
            Invalidate();
        }

        protected override void OnResize(EventArgs e)
        {
            base.OnResize(e);
            int radius = Math.Max(8, Height / 2);
            Ui.ApplyRound(this, radius);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Color border = _active ? Ui.PrimaryDeep : Ui.Line;
            int radius = Math.Max(8, Height / 2);
            Rectangle box = new Rectangle(0, 0, Math.Max(0, Width - 1), Math.Max(0, Height - 1));
            Ui.PaintRound(e.Graphics, box, radius, BackColor, border);
            TextRenderer.DrawText(
                e.Graphics,
                Text,
                Font,
                ClientRectangle,
                ForeColor,
                TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);
        }
    }

    internal sealed class ProjectCard : Control
    {
        public NamedItem Item;
        public bool Active;
        private bool _hover;

        public ProjectCard(NamedItem item)
        {
            Item = item;
            Size = new Size(236, 76);
            Margin = new Padding(0, 0, 10, 10);
            Cursor = Cursors.Hand;
            DoubleBuffered = true;
        }

        public void SetActive(bool active)
        {
            Active = active;
            Invalidate();
        }

        protected override void OnMouseEnter(EventArgs e)
        {
            _hover = true;
            Invalidate();
            base.OnMouseEnter(e);
        }

        protected override void OnMouseLeave(EventArgs e)
        {
            _hover = false;
            Invalidate();
            base.OnMouseLeave(e);
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            Graphics g = e.Graphics;
            g.SmoothingMode = SmoothingMode.AntiAlias;
            Color fill = Active ? Ui.ActiveCard : (_hover ? Ui.HoverCard : Color.White);
            Color border = Active ? Ui.Primary : Ui.Line;
            Rectangle box = new Rectangle(0, 0, Width - 1, Height - 1);
            Ui.PaintRound(g, box, 10, fill, border);
            if (Active)
            {
                using (Pen extra = new Pen(Ui.Primary))
                using (GraphicsPath path = Ui.RoundRect(box, 10))
                    g.DrawPath(extra, path);
            }

            Rectangle glyph = new Rectangle(12, 22, 32, 32);
            using (GraphicsPath gp = Ui.RoundRect(glyph, 8))
            using (SolidBrush brush = new SolidBrush(Ui.PrimarySoft))
                g.FillPath(brush, gp);
            using (Font glyphFont = new Font("Segoe UI", 8f, FontStyle.Bold))
            using (Font nameFont = new Font("Microsoft YaHei UI", 9f, FontStyle.Bold))
            using (Font pathFont = new Font("Microsoft YaHei UI", 7.5f))
            using (Font stateFont = new Font("Microsoft YaHei UI", 7f))
            {
                TextRenderer.DrawText(
                    g,
                    Ui.Glyph(Item != null ? Item.Title : "AG"),
                    glyphFont,
                    glyph,
                    Ui.Primary,
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.NoPadding);

                string name = Item != null ? Item.Title : "";
                string path = Item != null ? Item.Id : "";
                string state = Item != null ? Item.Kind : "";
                TextRenderer.DrawText(
                    g,
                    name,
                    nameFont,
                    new Rectangle(54, 12, Width - 66, 18),
                    Ui.Title,
                    TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
                TextRenderer.DrawText(
                    g,
                    path,
                    pathFont,
                    new Rectangle(54, 32, Width - 66, 16),
                    Ui.Mute,
                    TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);

                using (SolidBrush dot = new SolidBrush(Ui.StateColor(state)))
                    g.FillEllipse(dot, 54, 54, 8, 8);
                TextRenderer.DrawText(
                    g,
                    Ui.StateLabel(state),
                    stateFont,
                    new Rectangle(66, 50, Width - 78, 16),
                    Ui.Mute,
                    TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.VerticalCenter);
            }
        }
    }

    internal sealed class StateDot : Control
    {
        private string _state = "";

        public StateDot()
        {
            Size = new Size(18, 18);
            DoubleBuffered = true;
        }

        public void SetState(string state)
        {
            _state = state ?? "";
            Invalidate();
        }

        protected override void OnPaint(PaintEventArgs e)
        {
            e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
            e.Graphics.Clear(BackColor);
            using (Pen outline = new Pen(Ui.Line))
                e.Graphics.DrawEllipse(outline, 0, 0, 16, 16);
            using (SolidBrush ring = new SolidBrush(Ui.StateSoft(_state)))
                e.Graphics.FillEllipse(ring, 1, 1, 15, 15);
            using (SolidBrush core = new SolidBrush(Ui.StateColor(_state)))
                e.Graphics.FillEllipse(core, 5, 5, 7, 7);
        }
    }

    internal sealed class MainForm : Form
    {
        private const string StartupKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        private const string StartupValue = "AutoGovern2Code";
        private readonly HttpClient _http;
        private readonly string _token;
        private readonly string _runtime;
        private readonly JavaScriptSerializer _json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        private const int EM_SETCUEBANNER = 0x1501;
        private readonly Panel _loading;
        private readonly Label _loadingText;
        private readonly Label _status;
        private readonly FlowLayoutPanel _projectRail;
        private readonly Panel _empty;
        private readonly CardPanel _detail;
        private readonly Label _detailName;
        private readonly Label _detailPath;
        private readonly Label _detailHealth;
        private readonly StateDot _stateDot;
        private readonly Label _issues;
        private readonly TextBox _search;
        private readonly FlowLayoutPanel _filters;
        private readonly TreeView _tree;
        private readonly ListBox _cards;
        private readonly Label _inspectTitle;
        private readonly Label _inspectStatus;
        private readonly Label _inspectSummary;
        private readonly Label _inspectWho;
        private readonly Label _inspectFloors;
        private readonly Label _inspectWhen;
        private readonly Label _inspectRole;
        private readonly Label _inspectPath;
        private readonly Button _openFolder;
        private readonly Button _check;
        private readonly Button _stop;
        private readonly Button _resume;
        private readonly Button _uninstall;
        private readonly SplitContainer _graphSplit;
        private readonly SplitContainer _midSplit;
        private readonly Font _boldFont;
        private readonly Font _smallFont;
        private NotifyIcon _tray;
        private ToolStripMenuItem _startupItem;
        private Process _server;
        private string _baseUrl;
        private string _selectedRoot;
        private string _filterFlag = "";
        private bool _reallyExit;
        private bool _busy;
        private bool _portable;
        private Dictionary<string, object> _details;

        [DllImport("user32.dll")]
        private static extern bool SetForegroundWindow(IntPtr window);

        [DllImport("user32.dll")]
        private static extern bool DestroyIcon(IntPtr handle);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, string lParam);

        public static string AppDirectory()
        {
            return Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
        }

        public static bool IsPortable(string[] args)
        {
            if (args != null)
            {
                foreach (string arg in args)
                    if (String.Equals(arg, "--portable", StringComparison.OrdinalIgnoreCase))
                        return true;
            }
            string app = AppDirectory();
            return File.Exists(Path.Combine(app, "portable.ini"));
        }

        public MainForm(string[] args)
        {
            Text = "AutoGovern2Code";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(960, 640);
            ClientSize = new Size(1280, 860);
            BackColor = Ui.Page;
            ForeColor = Ui.Ink;
            Font = new Font("Microsoft YaHei UI", 9f);
            DoubleBuffered = true;
            Icon = CreateAppIcon();
            _token = CreateSessionToken();
            _runtime = ResolveRuntime(args);
            _portable = IsPortable(args);
            _http = new HttpClient(new HttpClientHandler { UseProxy = false });
            _http.Timeout = TimeSpan.FromSeconds(60);
            _boldFont = new Font("Microsoft YaHei UI", 9f, FontStyle.Bold);
            _smallFont = new Font("Microsoft YaHei UI", 7.5f);

            var shell = new Panel { Dock = DockStyle.Fill, Padding = new Padding(24, 20, 24, 24), BackColor = Ui.Page };

            var header = new CardPanel(10, Color.White, Ui.Line) { Dock = DockStyle.Top, Height = 52 };
            var mark = new Label
            {
                Text = "AG",
                Size = new Size(32, 32),
                Location = new Point(16, 10),
                BackColor = Ui.Primary,
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 8f, FontStyle.Bold),
                TextAlign = ContentAlignment.MiddleCenter
            };
            mark.Resize += delegate { Ui.ApplyRound(mark, 8); };
            var title = new Label
            {
                Text = "AutoGovern2Code",
                AutoSize = true,
                Location = new Point(58, 15),
                Font = new Font("Microsoft YaHei UI", 10.5f, FontStyle.Bold),
                ForeColor = Ui.Title,
                BackColor = Color.White
            };
            _status = new Label
            {
                AutoSize = true,
                Location = new Point(250, 18),
                ForeColor = Ui.Mute,
                BackColor = Color.White,
                Font = new Font("Microsoft YaHei UI", 9f),
                Text = "正在检查项目"
            };
            var refresh = new ChromeButton("刷新", "icon");
            refresh.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            var add = new ChromeButton("+  添加项目", "primary");
            add.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            header.Resize += delegate
            {
                add.Location = new Point(header.ClientSize.Width - add.Width - 16, 8);
                refresh.Location = new Point(add.Left - refresh.Width - 8, 8);
                _status.Location = new Point(Math.Min(250, Math.Max(title.Right + 16, add.Left - 280)), 18);
            };
            refresh.Click += async delegate { await RefreshProjectsAsync(); };
            add.Click += async delegate { await ChooseProjectAsync(); };
            header.Controls.Add(mark);
            header.Controls.Add(title);
            header.Controls.Add(_status);
            header.Controls.Add(refresh);
            header.Controls.Add(add);

            _projectRail = new FlowLayoutPanel
            {
                Dock = DockStyle.Top,
                AutoSize = true,
                AutoSizeMode = AutoSizeMode.GrowAndShrink,
                WrapContents = true,
                BackColor = Ui.Page,
                Padding = new Padding(0, 16, 0, 6)
            };

            _empty = new Panel { Dock = DockStyle.Fill, BackColor = Ui.Page, Visible = false };
            var emptyMark = new Label
            {
                Text = "+",
                AutoSize = false,
                Size = new Size(48, 48),
                Font = new Font("Segoe UI", 22f),
                ForeColor = Color.FromArgb(156, 163, 175),
                TextAlign = ContentAlignment.MiddleCenter,
                BackColor = Ui.Page
            };
            var emptyTitle = new Label
            {
                Text = "还没有治理项目",
                AutoSize = false,
                Size = new Size(280, 28),
                Font = _boldFont,
                ForeColor = Ui.SecondaryText,
                TextAlign = ContentAlignment.MiddleCenter,
                BackColor = Ui.Page
            };
            var emptyAdd = new ChromeButton("添加项目", "primary");
            emptyAdd.Click += async delegate { await ChooseProjectAsync(); };
            _empty.Controls.Add(emptyMark);
            _empty.Controls.Add(emptyTitle);
            _empty.Controls.Add(emptyAdd);
            _empty.Resize += delegate
            {
                emptyMark.Location = new Point((_empty.ClientSize.Width - emptyMark.Width) / 2, Math.Max(40, (_empty.ClientSize.Height - 140) / 2));
                emptyTitle.Location = new Point((_empty.ClientSize.Width - emptyTitle.Width) / 2, emptyMark.Bottom + 8);
                emptyAdd.Location = new Point((_empty.ClientSize.Width - emptyAdd.Width) / 2, emptyTitle.Bottom + 18);
            };

            _detail = new CardPanel(12, Color.White, Ui.Line) { Dock = DockStyle.Fill };

            var titleRow = new Panel { Dock = DockStyle.Top, Height = 48, BackColor = Color.White, Padding = new Padding(20, 12, 12, 0) };
            _detailName = new Label
            {
                AutoSize = false,
                Height = 36,
                Dock = DockStyle.Fill,
                Font = new Font("Microsoft YaHei UI", 15f, FontStyle.Bold),
                ForeColor = Ui.Title,
                Text = "选择一个项目",
                TextAlign = ContentAlignment.MiddleLeft,
                BackColor = Color.White
            };
            var actions = new FlowLayoutPanel
            {
                Dock = DockStyle.Right,
                Width = 430,
                WrapContents = false,
                BackColor = Color.White,
                Padding = new Padding(0, 0, 4, 0),
                FlowDirection = FlowDirection.LeftToRight
            };
            _openFolder = new ChromeButton("打开文件夹", "icon");
            _check = new ChromeButton("重新检查", "secondary");
            _stop = new ChromeButton("停止治理", "danger");
            _resume = new ChromeButton("恢复治理", "secondary");
            _uninstall = new ChromeButton("卸载项目", "secondary");
            _openFolder.Click += delegate { OpenSelectedFolder(); };
            _check.Click += async delegate { await PostProjectAsync("/api/projects/check"); };
            _stop.Click += async delegate { await ConfirmPostAsync("停止治理后，这个仓库不再被 AG2C 拦截提交。证据还在。", "/api/projects/remove"); };
            _resume.Click += async delegate { await PostProjectAsync("/api/projects/resume"); };
            _uninstall.Click += async delegate { await ConfirmPostAsync("卸载项目会删除这份治理档案，不能恢复。仓库源码不会被删。", "/api/projects/uninstall"); };
            actions.Controls.AddRange(new Control[] { _openFolder, _check, _stop, _resume, _uninstall });
            titleRow.Controls.Add(_detailName);
            titleRow.Controls.Add(actions);

            _detailPath = new Label
            {
                AutoSize = false,
                Height = 20,
                Dock = DockStyle.Top,
                ForeColor = Ui.Mute,
                Font = _smallFont,
                Padding = new Padding(20, 0, 20, 0),
                BackColor = Color.White
            };
            var healthRow = new Panel { Dock = DockStyle.Top, Height = 36, BackColor = Color.White, Padding = new Padding(20, 8, 20, 0) };
            _stateDot = new StateDot { Location = new Point(20, 10), BackColor = Color.White };
            _detailHealth = new Label
            {
                AutoSize = false,
                Location = new Point(46, 8),
                Size = new Size(640, 22),
                Font = new Font("Microsoft YaHei UI", 9f, FontStyle.Bold),
                ForeColor = Color.FromArgb(22, 101, 52),
                Text = "尚未加载",
                BackColor = Color.White
            };
            healthRow.Controls.Add(_stateDot);
            healthRow.Controls.Add(_detailHealth);
            healthRow.Resize += delegate { _detailHealth.Width = Math.Max(120, healthRow.ClientSize.Width - 60); };

            _issues = new Label
            {
                AutoSize = false,
                Height = 0,
                Dock = DockStyle.Top,
                ForeColor = Ui.IssueText,
                BackColor = Ui.IssueBg,
                Padding = new Padding(24, 8, 12, 8),
                Font = new Font("Microsoft YaHei UI", 8f),
                Visible = false
            };

            var tools = new Panel { Dock = DockStyle.Top, Height = 92, BackColor = Color.White, Padding = new Padding(20, 4, 16, 4) };
            var searchLabel = new Label
            {
                Text = "找文件",
                AutoSize = true,
                Location = new Point(20, 12),
                Font = _boldFont,
                ForeColor = Ui.Ink,
                BackColor = Color.White
            };
            _search = new TextBox { Width = 280, Location = new Point(70, 8), Height = 24, BorderStyle = BorderStyle.FixedSingle };
            _search.TextChanged += delegate { RenderCoverage(); };
            _search.HandleCreated += delegate
            {
                SendMessage(_search.Handle, EM_SETCUEBANNER, (IntPtr)1, "frontend、css、文件名或知识卡");
            };
            var expand = new ChromeButton("展开全部", "secondary");
            expand.Location = new Point(360, 6);
            expand.Click += delegate { _tree.ExpandAll(); };
            _filters = new FlowLayoutPanel
            {
                Location = new Point(16, 44),
                Height = 40,
                WrapContents = true,
                BackColor = Color.White
            };
            string[] chipLabels = { "全部", "开工", "黑盒", "无主", "过期", "未普查", "重复认领", "废弃未清", "未验收", "AI正在写" };
            string[] chipFlags = { "", "exploring", "opaque", "unowned", "stale", "unreviewed", "ambiguous", "abandoned", "undeclared", "writing" };
            for (int i = 0; i < chipLabels.Length; i++)
            {
                ChipButton chip = new ChipButton(chipLabels[i], chipFlags[i]);
                chip.Click += ChipClicked;
                _filters.Controls.Add(chip);
            }
            tools.Controls.Add(searchLabel);
            tools.Controls.Add(_search);
            tools.Controls.Add(expand);
            tools.Controls.Add(_filters);
            tools.Resize += delegate
            {
                _filters.Width = Math.Max(200, tools.ClientSize.Width - 36);
                expand.Location = new Point(Math.Max(360, tools.ClientSize.Width - expand.Width - 20), 6);
            };

            _graphSplit = new SplitContainer
            {
                Dock = DockStyle.Fill,
                SplitterWidth = 1,
                BackColor = Ui.Line
            };
            var treeHost = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            treeHost.Controls.Add(PaneHeader("项目文件树", Color.White));
            _tree = new TreeView
            {
                Dock = DockStyle.Fill,
                BorderStyle = BorderStyle.None,
                BackColor = Color.White,
                FullRowSelect = true,
                HideSelection = false,
                ShowLines = false,
                ItemHeight = 22,
                DrawMode = TreeViewDrawMode.OwnerDrawText,
                Font = new Font("Microsoft YaHei UI", 8.5f)
            };
            _tree.DrawNode += DrawTreeNode;
            _tree.AfterSelect += delegate { InspectNode(_tree.SelectedNode); };
            treeHost.Controls.Add(_tree);
            treeHost.Controls.SetChildIndex(_tree, 0);
            _graphSplit.Panel1.Controls.Add(treeHost);

            _midSplit = new SplitContainer
            {
                Dock = DockStyle.Fill,
                SplitterWidth = 1,
                BackColor = Ui.Line
            };
            var cardHost = new Panel { Dock = DockStyle.Fill, BackColor = Ui.CardPane };
            cardHost.Controls.Add(PaneHeader("知识卡片", Ui.CardPane));
            _cards = new ListBox
            {
                Dock = DockStyle.Fill,
                IntegralHeight = false,
                BorderStyle = BorderStyle.None,
                BackColor = Ui.CardPane,
                DrawMode = DrawMode.OwnerDrawVariable,
                Font = new Font("Microsoft YaHei UI", 8.5f)
            };
            _cards.MeasureItem += MeasureCard;
            _cards.DrawItem += DrawCard;
            _cards.SelectedIndexChanged += delegate { InspectCard(_cards.SelectedItem as NamedItem); };
            cardHost.Controls.Add(_cards);
            cardHost.Controls.SetChildIndex(_cards, 0);

            var inspector = new Panel { Dock = DockStyle.Fill, BackColor = Color.White, AutoScroll = true, Padding = new Padding(16) };
            inspector.Controls.Add(PaneHeader("详情", Color.White));
            var inspectBody = new FlowLayoutPanel
            {
                Dock = DockStyle.Fill,
                FlowDirection = FlowDirection.TopDown,
                WrapContents = false,
                AutoScroll = true,
                BackColor = Color.White,
                Padding = new Padding(16, 8, 16, 16)
            };
            _inspectTitle = InspectHead("点文件树或右边的知识卡", true);
            _inspectStatus = InspectHead("左边先把项目文件看清楚。搜 frontend 会只留下前端路径。", false);
            _inspectStatus.ForeColor = Ui.Mute;
            _inspectStatus.Font = _smallFont;
            _inspectSummary = InspectHead("", false);
            _inspectSummary.ForeColor = Ui.Mute;
            _inspectSummary.Font = _smallFont;
            inspectBody.Controls.Add(_inspectTitle);
            inspectBody.Controls.Add(_inspectStatus);
            inspectBody.Controls.Add(_inspectSummary);
            _inspectWho = AddInspectRow(inspectBody, "谁管理");
            _inspectFloors = AddInspectRow(inspectBody, "属于哪几个楼层");
            _inspectWhen = AddInspectRow(inspectBody, "最近一次提交");
            _inspectRole = AddInspectRow(inspectBody, "现在是不是多余的");
            _inspectPath = AddInspectRow(inspectBody, "路径");
            inspectBody.Resize += delegate
            {
                int inner = Math.Max(120, inspectBody.ClientSize.Width - 8);
                foreach (Control child in inspectBody.Controls)
                    child.Width = inner;
            };
            inspector.Controls.Add(inspectBody);
            inspector.Controls.SetChildIndex(inspectBody, 0);
            _midSplit.Panel1.Controls.Add(cardHost);
            _midSplit.Panel2.Controls.Add(inspector);
            _graphSplit.Panel2.Controls.Add(_midSplit);

            _detail.Controls.Add(_graphSplit);
            _detail.Controls.Add(tools);
            _detail.Controls.Add(_issues);
            _detail.Controls.Add(healthRow);
            _detail.Controls.Add(_detailPath);
            _detail.Controls.Add(titleRow);

            shell.Controls.Add(_detail);
            shell.Controls.Add(_empty);
            shell.Controls.Add(_projectRail);
            shell.Controls.Add(header);

            _loading = new Panel { Dock = DockStyle.Fill, BackColor = Color.White };
            var loadMark = new Label
            {
                Text = "AG",
                Size = new Size(74, 74),
                BackColor = Ui.Primary,
                ForeColor = Color.White,
                Font = new Font("Segoe UI", 22f, FontStyle.Bold),
                TextAlign = ContentAlignment.MiddleCenter
            };
            loadMark.Resize += delegate { Ui.ApplyRound(loadMark, 12); };
            _loadingText = new Label
            {
                AutoSize = false,
                Size = new Size(420, 52),
                Text = "正在检查治理项目...",
                ForeColor = Ui.Mute,
                Font = new Font("Microsoft YaHei UI", 11f),
                TextAlign = ContentAlignment.MiddleCenter,
                BackColor = Color.White
            };
            _loading.Controls.Add(loadMark);
            _loading.Controls.Add(_loadingText);
            _loading.Resize += delegate
            {
                loadMark.Location = new Point((_loading.ClientSize.Width - loadMark.Width) / 2, Math.Max(40, (_loading.ClientSize.Height - 150) / 2));
                _loadingText.Location = new Point((_loading.ClientSize.Width - _loadingText.Width) / 2, loadMark.Bottom + 18);
                Ui.ApplyRound(loadMark, 12);
            };

            Controls.Add(shell);
            Controls.Add(_loading);
            _loading.BringToFront();
            SetupTray();
            FormClosing += OnFormClosing;
            Shown += async delegate
            {
                Ui.ApplyRound(mark, 8);
                Ui.ApplyRound(loadMark, 12);
                LayoutGraph();
                PaintChips();
                await StartDesktopAsync();
            };
        }

        private static Label PaneHeader(string text, Color back)
        {
            return new Label
            {
                Text = text,
                Dock = DockStyle.Top,
                Height = 32,
                Padding = new Padding(12, 8, 12, 0),
                Font = new Font("Microsoft YaHei UI", 8f, FontStyle.Bold),
                ForeColor = Color.FromArgb(31, 42, 39),
                BackColor = back
            };
        }

        private static Label InspectHead(string text, bool title)
        {
            return new Label
            {
                Text = text,
                AutoSize = false,
                Height = title ? 36 : 32,
                Font = new Font("Microsoft YaHei UI", title ? 9f : 8f, title ? FontStyle.Bold : FontStyle.Regular),
                ForeColor = title ? Ui.Title : Ui.Mute,
                BackColor = Color.White
            };
        }

        private static Label AddInspectRow(Control host, string key)
        {
            var wrap = new Panel { Height = 46, BackColor = Color.White };
            wrap.Paint += delegate(object sender, PaintEventArgs e)
            {
                using (Pen pen = new Pen(Color.FromArgb(243, 244, 246)))
                    e.Graphics.DrawLine(pen, 0, 0, wrap.Width, 0);
            };
            var dt = new Label
            {
                Text = key,
                Dock = DockStyle.Top,
                Height = 16,
                ForeColor = Color.FromArgb(156, 163, 175),
                Font = new Font("Microsoft YaHei UI", 7f),
                BackColor = Color.White
            };
            var dd = new Label
            {
                Dock = DockStyle.Fill,
                ForeColor = Ui.SecondaryText,
                Font = new Font("Microsoft YaHei UI", 8.5f),
                Text = "—",
                BackColor = Color.White
            };
            wrap.Controls.Add(dd);
            wrap.Controls.Add(dt);
            host.Controls.Add(wrap);
            return dd;
        }

        private void LayoutGraph()
        {
            PlaceSplitter(_graphSplit, 180, 280, (int)(_graphSplit.Width * 0.42));
            PlaceSplitter(_midSplit, 160, 240, _midSplit.Width - 320);
        }

        private static void PlaceSplitter(SplitContainer split, int leftMin, int rightMin, int preferredLeft)
        {
            if (split == null) return;
            int width = split.Width;
            int gutter = Math.Max(1, split.SplitterWidth);
            if (width <= leftMin + rightMin + gutter) return;
            int panel1 = Math.Min(leftMin, width / 4);
            int panel2 = Math.Min(rightMin, width / 4);
            int maxLeft = width - panel2 - gutter;
            int minLeft = panel1;
            int left = preferredLeft;
            if (left < minLeft) left = minLeft;
            if (left > maxLeft) left = maxLeft;
            split.SplitterDistance = left;
            split.Panel1MinSize = panel1;
            split.Panel2MinSize = panel2;
        }

        private void PaintChips()
        {
            foreach (Control control in _filters.Controls)
            {
                ChipButton chip = control as ChipButton;
                if (chip != null) chip.SetActive(chip.Flag == _filterFlag);
            }
        }

        private void ChipClicked(object sender, EventArgs e)
        {
            ChipButton chip = sender as ChipButton;
            if (chip == null) return;
            _filterFlag = chip.Flag ?? "";
            PaintChips();
            RenderCoverage();
        }

        private async void ProjectCardClicked(object sender, EventArgs e)
        {
            ProjectCard card = sender as ProjectCard;
            if (card == null || card.Item == null) return;
            SelectProject(card.Item.Id);
            await LoadSelectedAsync();
        }

        private static Button MakeButton(string text, bool primary)
        {
            return new ChromeButton(text, primary ? "primary" : "secondary");
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
            if (_portable)
            {
                string home = AppDirectory();
                start.EnvironmentVariables["AG2C_PORTABLE"] = home;
                start.EnvironmentVariables["AG2C_DATA_ROOT"] = Path.Combine(home, "data");
                start.EnvironmentVariables["AG2C_PORTABLE_GIT"] = Path.Combine(home, "git");
            }
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
            foreach (Control control in _projectRail.Controls)
            {
                ProjectCard card = control as ProjectCard;
                if (card != null && card.Item != null && card.Item.Id == _selectedRoot)
                    return card.Item;
            }
            return null;
        }

        private void SelectProject(string root)
        {
            _selectedRoot = root;
            foreach (Control control in _projectRail.Controls)
            {
                ProjectCard card = control as ProjectCard;
                if (card != null && card.Item != null)
                    card.SetActive(card.Item.Id == _selectedRoot);
            }
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
                string selected = _selectedRoot;
                _projectRail.SuspendLayout();
                _projectRail.Controls.Clear();
                int count = 0;
                ArrayList list = payload != null ? payload["projects"] as ArrayList : null;
                if (list != null)
                {
                    foreach (object raw in list)
                    {
                        Dictionary<string, object> row = raw as Dictionary<string, object>;
                        if (row == null) continue;
                        NamedItem item = new NamedItem();
                        item.Id = Str(row, "root");
                        item.Title = Str(row, "name");
                        item.Kind = Str(row, "state");
                        item.Data = row;
                        ProjectCard card = new ProjectCard(item);
                        card.Click += ProjectCardClicked;
                        _projectRail.Controls.Add(card);
                        count++;
                    }
                }
                _projectRail.ResumeLayout();
                bool empty = count == 0;
                _empty.Visible = empty;
                _detail.Visible = !empty;
                _status.Text = empty ? "还没有治理项目" : ("已接入 " + count + " 个项目");
                if (!empty)
                {
                    bool found = false;
                    if (!string.IsNullOrEmpty(selected))
                    {
                        foreach (Control control in _projectRail.Controls)
                        {
                            ProjectCard card = control as ProjectCard;
                            if (card != null && card.Item != null && card.Item.Id == selected)
                            {
                                found = true;
                                break;
                            }
                        }
                    }
                    if (!found)
                    {
                        ProjectCard first = _projectRail.Controls.Count > 0 ? _projectRail.Controls[0] as ProjectCard : null;
                        selected = first != null && first.Item != null ? first.Item.Id : null;
                    }
                    SelectProject(selected);
                    await LoadSelectedAsync();
                }
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
            string state = Str(project.Data, "state");
            _detailName.Text = Str(project.Data, "name");
            _detailPath.Text = Str(project.Data, "root");
            _detailHealth.Text = Ui.StateLabel(state);
            _detailHealth.ForeColor = state == "protected" ? Color.FromArgb(22, 101, 52) : Ui.SecondaryText;
            _stateDot.SetState(state);
            string[] issues = Strings(project.Data, "issues");
            if (issues.Length == 0)
            {
                _issues.Visible = false;
                _issues.Height = 0;
                _issues.Text = "";
            }
            else
            {
                _issues.Text = "!  " + string.Join("；", issues);
                _issues.Visible = true;
                _issues.Height = 36;
            }
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
                ShowInspect("无法加载详情", error.Message, "", "", "", "", "", "");
            }
        }

        private string FilterFlag()
        {
            return _filterFlag ?? "";
        }

        private void RenderCoverage()
        {
            _tree.BeginUpdate();
            _tree.Nodes.Clear();
            _cards.Items.Clear();
            if (_details == null)
            {
                _tree.EndUpdate();
                ShowInspect("选择一个项目", "选择一个项目后，这里显示谁管理文件、是不是开工或黑盒。", "", "", "", "", "", "");
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
                        card.Kind = FirstFlagLabel(node);
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
            ShowInspect(
                "点文件树或右边的知识卡",
                headline != null ? Convert.ToString(headline) : "点文件树或知识卡查看归属。",
                "",
                "—",
                "—",
                "—",
                "—",
                "—");
        }

        private void DrawTreeNode(object sender, DrawTreeNodeEventArgs e)
        {
            bool selected = (e.State & TreeNodeStates.Selected) != 0;
            Color back = selected ? Ui.PrimaryHover : _tree.BackColor;
            Rectangle row = new Rectangle(0, e.Bounds.Y, _tree.ClientSize.Width, e.Bounds.Height);
            using (SolidBrush brush = new SolidBrush(back))
                e.Graphics.FillRectangle(brush, row);
            Font font = e.Node.Nodes.Count > 0 ? _boldFont : _tree.Font;
            TextRenderer.DrawText(
                e.Graphics,
                e.Node.Text,
                font,
                e.Bounds,
                Ui.Ink,
                TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding | TextFormatFlags.GlyphOverhangPadding);
            Dictionary<string, object> data = e.Node.Tag as Dictionary<string, object>;
            if (data != null)
            {
                string badge = Str(data, "coverageLabel");
                if (badge.Length == 0) badge = FirstFlagLabel(data);
                if (badge.Length > 0)
                {
                    Rectangle right = new Rectangle(e.Bounds.Right, e.Bounds.Y, Math.Max(40, _tree.ClientSize.Width - e.Bounds.Right - 8), e.Bounds.Height);
                    TextRenderer.DrawText(
                        e.Graphics,
                        badge,
                        _smallFont,
                        right,
                        Ui.PrimaryDeep,
                        TextFormatFlags.VerticalCenter | TextFormatFlags.Right | TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
                }
            }
        }

        private void MeasureCard(object sender, MeasureItemEventArgs e)
        {
            e.ItemHeight = 64;
        }

        private void DrawCard(object sender, DrawItemEventArgs e)
        {
            if (e.Index < 0 || e.Index >= _cards.Items.Count) return;
            NamedItem item = _cards.Items[e.Index] as NamedItem;
            bool selected = (e.State & DrawItemState.Selected) != 0;
            Color back = selected ? Ui.PrimaryHover : Ui.CardPane;
            using (SolidBrush brush = new SolidBrush(back))
                e.Graphics.FillRectangle(brush, e.Bounds);
            using (Pen pen = new Pen(Color.FromArgb(243, 244, 246)))
                e.Graphics.DrawLine(pen, e.Bounds.Left, e.Bounds.Bottom - 1, e.Bounds.Right, e.Bounds.Bottom - 1);
            if (item == null) return;
            Rectangle title = new Rectangle(e.Bounds.X + 12, e.Bounds.Y + 10, e.Bounds.Width - 24, 20);
            Rectangle meta = new Rectangle(e.Bounds.X + 12, e.Bounds.Y + 32, e.Bounds.Width - 24, 20);
            TextRenderer.DrawText(e.Graphics, item.Title, _boldFont, title, Ui.Title, TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
            string extra = item.Kind ?? "";
            if (item.Data != null)
            {
                string path = Str(item.Data, "path");
                if (path.Length > 0)
                    extra = extra.Length > 0 ? extra + "  ·  " + path : path;
            }
            TextRenderer.DrawText(e.Graphics, extra, _smallFont, meta, Ui.Mute, TextFormatFlags.EndEllipsis | TextFormatFlags.NoPadding);
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
            if (flag == "ambiguous") return "重复认领";
            if (flag == "undeclared") return "未验收";
            if (flag == "writing") return "AI正在写";
            return flag;
        }

        private void InspectNode(TreeNode node)
        {
            if (node == null) return;
            Dictionary<string, object> data = node.Tag as Dictionary<string, object>;
            if (data == null) return;
            BindInspect(data);
        }

        private void InspectCard(NamedItem card)
        {
            if (card == null || card.Data == null) return;
            BindInspect(card.Data);
        }

        private void BindInspect(Dictionary<string, object> node)
        {
            string title = Str(node, "title");
            if (title.Length == 0) title = Str(node, "path");
            string who = Str(node, "coverageLabel");
            if (who.Length == 0) who = Join(node, "coveredBy");
            string floors = Join(node, "floors");
            if (floors == "—") floors = Str(node, "floorLabel");
            string when = Str(node, "lastCommit");
            if (when.Length == 0) when = Str(node, "changedAt");
            string role = Str(node, "roleLabel");
            if (role.Length == 0) role = FirstFlagLabel(node);
            ShowInspect(
                title,
                FirstFlagLabel(node),
                Str(node, "summary"),
                who,
                floors,
                when,
                role,
                Str(node, "path"));
        }

        private void ShowInspect(string title, string status, string summary, string who, string floors, string when, string role, string path)
        {
            _inspectTitle.Text = string.IsNullOrEmpty(title) ? "点文件树或右边的知识卡" : title;
            _inspectStatus.Text = status ?? "";
            _inspectSummary.Text = summary ?? "";
            _inspectWho.Text = Dash(who);
            _inspectFloors.Text = Dash(floors);
            _inspectWhen.Text = Dash(when);
            _inspectRole.Text = Dash(role);
            _inspectPath.Text = Dash(path);
        }

        private static string Dash(string value)
        {
            if (string.IsNullOrEmpty(value) || value == "—") return "—";
            return value;
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
            if (!_portable)
            {
                menu.Items.Add(new ToolStripSeparator());
                _startupItem = new ToolStripMenuItem("登录 Windows 后启动") { Checked = StartupEnabled(), CheckOnClick = true };
                _startupItem.CheckedChanged += delegate { ApplyStartup(_startupItem.Checked); };
                menu.Items.Add(_startupItem);
            }
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
                graphics.Clear(Color.FromArgb(37, 99, 235));
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
