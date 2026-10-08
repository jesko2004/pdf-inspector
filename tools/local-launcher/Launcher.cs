using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Cache;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32.SafeHandles;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class OwnedProcesses : IDisposable
{
    [StructLayout(LayoutKind.Sequential)] private struct BasicLimits
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }
    [StructLayout(LayoutKind.Sequential)] private struct IoCounters
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount;
        public ulong ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }
    [StructLayout(LayoutKind.Sequential)] private struct ExtendedLimits
    {
        public BasicLimits BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateJobObject(IntPtr attributes, string name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(SafeFileHandle job, int type, IntPtr info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(SafeFileHandle job, IntPtr process);
    private readonly SafeFileHandle handle;
    public OwnedProcesses()
    {
        handle = CreateJobObject(IntPtr.Zero, null);
        if (handle.IsInvalid) throw new System.ComponentModel.Win32Exception();
        var info = new ExtendedLimits();
        info.BasicLimitInformation.LimitFlags = 0x2000; // KILL_ON_JOB_CLOSE; only children we start.
        int size = Marshal.SizeOf(info);
        IntPtr buffer = Marshal.AllocHGlobal(size);
        try
        {
            Marshal.StructureToPtr(info, buffer, false);
            if (!SetInformationJobObject(handle, 9, buffer, (uint)size))
                throw new System.ComponentModel.Win32Exception();
        }
        catch { handle.Dispose(); throw; }
        finally { Marshal.FreeHGlobal(buffer); }
    }
    public void Add(Process process)
    {
        if (!AssignProcessToJobObject(handle, process.Handle))
        {
            int error = Marshal.GetLastWin32Error();
            try { process.Kill(); } catch (InvalidOperationException) { }
            throw new System.ComponentModel.Win32Exception(error, "无法管理启动进程，已取消启动。");
        }
    }
    public void Dispose() { handle.Dispose(); }
}

internal sealed class LocalRunner : IDisposable
{
    public readonly string Root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
    public readonly string Control;
    public string LogPath { get { return Path.Combine(Control, "service.log"); } }
    private string UiPath { get { return Path.Combine(Root, "backend", "static", "manual.html"); } }
    public string PageUrl
    {
        get
        {
            using (var sha = SHA256.Create())
            {
                string version = BitConverter.ToString(sha.ComputeHash(File.ReadAllBytes(UiPath))).Replace("-", "").ToLowerInvariant();
                return "http://127.0.0.1:8000/demo?ui=" + version + "&session=" + Path.GetFileName(Control);
            }
        }
    }
    public Process Server;
    public bool Ready { get { return File.Exists(Path.Combine(Control, "ready.json")); } }
    private readonly object logLock = new object();
    private OwnedProcesses owned;
    private bool disposed;
    public LocalRunner()
    {
        Control = Path.Combine(Root, "tmp", "local-launcher", Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Control);
        owned = new OwnedProcesses();
    }
    private static string QuotePS(string value) { return "'" + value.Replace("'", "''") + "'"; }
    private void Log(object sender, DataReceivedEventArgs e)
    {
        if (e.Data == null) return;
        lock (logLock) File.AppendAllText(LogPath, e.Data + Environment.NewLine, Encoding.UTF8);
    }
    private Process Start(ProcessStartInfo info)
    {
        info.WorkingDirectory = Root;
        info.UseShellExecute = false;
        info.CreateNoWindow = true;
        info.RedirectStandardOutput = true;
        info.RedirectStandardError = true;
        info.StandardOutputEncoding = Encoding.UTF8;
        info.StandardErrorEncoding = Encoding.UTF8;
        var process = new Process { StartInfo = info };
        process.OutputDataReceived += Log;
        process.ErrorDataReceived += Log;
        if (!process.Start()) throw new InvalidOperationException("无法启动本机服务。");
        owned.Add(process);
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        return process;
    }
    public static string Get(string url)
    {
        string cacheControl;
        return Get(url, out cacheControl);
    }
    private static string Get(string url, out string cacheControl)
    {
        var request = (HttpWebRequest)WebRequest.Create(url);
        request.Proxy = null;
        request.CachePolicy = new RequestCachePolicy(RequestCacheLevel.BypassCache);
        request.Timeout = 2000;
        request.ReadWriteTimeout = 2000;
        using (var response = request.GetResponse())
        {
            cacheControl = response.Headers[HttpResponseHeader.CacheControl] ?? "";
            using (var reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
                return reader.ReadToEnd();
        }
    }
    public string VerifyPage()
    {
        string cacheControl;
        string html = Get(PageUrl, out cacheControl);
        if (!cacheControl.Contains("no-store") || html != File.ReadAllText(UiPath, Encoding.UTF8) ||
            html.Contains("value=\"资料查询\"") ||
            !html.Contains("id=\"uploadTarget\"") ||
            !html.Contains("id=\"documentScope\"") ||
            !html.Contains("id=\"deleteKb\"") ||
            !html.Contains("placeholder=\"请输入知识库名称\""))
            throw new InvalidOperationException("未能加载新版资料库页面。请检查项目文件是否完整，再重新启动。");
        return html;
    }
    private static bool PortInUse(int port)
    {
        var listener = new TcpListener(IPAddress.Loopback, port);
        try { listener.Start(); return false; }
        catch (SocketException) { return true; }
        finally { listener.Stop(); }
    }
    public void StartServer(string dataDirectory)
    {
        string python = Path.Combine(Root, ".codex-tools", "api-venv", "Scripts", "python.exe");
        string config = Path.Combine(Root, ".codex-tools", "use-ollama.ps1");
        if (!File.Exists(config)) config = Path.Combine(Root, "tools", "local-launcher", "use-ollama.ps1");
        string controller = Path.Combine(Root, "tools", "local-launcher", "server_control.py");
        if (!File.Exists(python) || !File.Exists(config) || !File.Exists(controller) || !File.Exists(UiPath))
            throw new InvalidOperationException("启动环境不完整。请将程序放在项目根目录，保留配套文件；首次使用请按 README 的桌面端步骤准备环境。");
        if (PortInUse(8000))
            throw new InvalidOperationException("8000 端口已被使用。请先关闭原来的资料库服务，再启动；本启动器不会终止已有服务。");
        string tags = null;
        try { tags = Get("http://127.0.0.1:11434/api/tags"); } catch (WebException) { }
        if (tags == null)
        {
            if (PortInUse(11434)) throw new InvalidOperationException("11434 端口已被占用，但 Ollama 没有正常响应。");
            string ollama = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Ollama", "ollama.exe");
            if (!File.Exists(ollama)) ollama = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Ollama", "ollama.exe");
            if (!File.Exists(ollama)) throw new InvalidOperationException("没有找到 Ollama。请先打开已安装的 Ollama，再重试。");
            var info = new ProcessStartInfo(ollama, "serve");
            info.EnvironmentVariables["OLLAMA_HOST"] = "127.0.0.1:11434";
            Process modelServer = Start(info);
            for (int i = 0; i < 60 && tags == null; i++)
            {
                if (modelServer.HasExited) throw new InvalidOperationException("Ollama 启动失败，请查看日志。");
                Thread.Sleep(500);
                try { tags = Get("http://127.0.0.1:11434/api/tags"); } catch (WebException) { }
            }
            if (tags == null) throw new InvalidOperationException("等待 Ollama 启动超时，请查看日志后重试。");
        }
        var json = new JavaScriptSerializer();
        var parsed = json.Deserialize<Dictionary<string, object>>(tags);
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (object item in (System.Collections.ArrayList)parsed["models"])
            names.Add((string)((Dictionary<string, object>)item)["name"]);
        foreach (string name in new[] { "qwen3-embedding:0.6b", "pdf-inspector-qwen3-instruct:4b" })
            if (!names.Contains(name)) throw new InvalidOperationException("缺少本机模型：" + name + "。请恢复原有模型后重试。");
        string command = "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; " +
            "$OutputEncoding=[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding; . " + QuotePS(config) + "; " +
            "$env:PDF_INSPECTOR_PORT='8000'; $env:PYTHONIOENCODING='utf-8'; ";
        if (dataDirectory != null) command += "$env:PDF_INSPECTOR_DATA_DIR=" + QuotePS(dataDirectory) + "; ";
        command += "& " + QuotePS(python) + " -u " + QuotePS(controller) + " " + QuotePS(Control) + "; exit $LASTEXITCODE";
        string encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(command));
        string powershell = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");
        Server = Start(new ProcessStartInfo(powershell, "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand " + encoded));
    }
    public bool Stop()
    {
        File.WriteAllText(Path.Combine(Control, "stop"), "stop", Encoding.UTF8);
        bool graceful = Server == null || Server.HasExited || Server.WaitForExit(20000);
        if (graceful && Server != null) Server.WaitForExit(); // Flush redirected log handlers.
        Dispose();
        return graceful;
    }
    public void Dispose()
    {
        if (disposed) return;
        disposed = true;
        owned.Dispose();
    }
}

internal sealed class LauncherForm : Form
{
    private readonly Label status = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft, Padding = new Padding(18, 0, 0, 0), Text = "正在启动资料库…" };
    private readonly Label message = new Label { Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleCenter, Padding = new Padding(40), Text = "正在检查本机环境并加载资料，请稍候…" };
    private readonly Button reload = new Button { Text = "重新加载", Dock = DockStyle.Right, Width = 105, Enabled = false };
    private readonly Button retry = new Button { Text = "重试启动", Dock = DockStyle.Right, Width = 105, Visible = false };
    private readonly WebView2 view = new WebView2 { Dock = DockStyle.Fill, Visible = false, DefaultBackgroundColor = Color.FromArgb(246, 248, 252) };
    private readonly Panel content = new Panel { Dock = DockStyle.Fill };
    private readonly DesktopSmoke smoke;
    private LocalRunner runner;
    private readonly System.Windows.Forms.Timer timer = new System.Windows.Forms.Timer { Interval = 500 };
    private Task startup;
    private bool closing, stopped, initialized;
    public LauncherForm(DesktopSmoke test)
    {
        smoke = test;
        Text = "PDF 资料库 · 桌面版 2026.10.08.4";
        Font = new Font("Microsoft YaHei UI", 10);
        ClientSize = new Size(1120, 820);
        MinimumSize = new Size(760, 600);
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterScreen;
        var toolbar = new Panel { Dock = DockStyle.Top, Height = 48, Padding = new Padding(0, 6, 10, 6), BackColor = Color.White };
        var logs = new Button { Text = "查看日志", Dock = DockStyle.Right, Width = 105 };
        toolbar.Controls.Add(status); toolbar.Controls.Add(retry); toolbar.Controls.Add(reload); toolbar.Controls.Add(logs);
        content.Controls.Add(view); content.Controls.Add(message);
        Controls.Add(content); Controls.Add(toolbar);
        logs.Click += delegate { if (runner != null && File.Exists(runner.LogPath)) Process.Start(new ProcessStartInfo("notepad.exe", "\"" + runner.LogPath + "\"") { UseShellExecute = true }); };
        reload.Click += async delegate { try { await LoadPage(); } catch (Exception error) { ShowFailure(error.Message); } };
        retry.Click += delegate { startup = StartDesktop(); };
        Shown += delegate { startup = StartDesktop(); };
        FormClosing += OnClosing;
        timer.Tick += delegate
        {
            if (!closing && runner != null && runner.Server != null && runner.Server.HasExited)
            { timer.Stop(); ShowFailure("资料库服务已退出。资料保存在本机，请点击“重试启动”。"); retry.Visible = true; }
        };
    }
    private static bool IsLocalPage(string address)
    {
        Uri uri;
        return Uri.TryCreate(address, UriKind.Absolute, out uri) && uri.Scheme == "http" &&
            uri.Host == "127.0.0.1" && uri.Port == 8000 && uri.AbsolutePath == "/demo";
    }
    private async Task InitializeView()
    {
        if (initialized) return;
        CoreWebView2Environment.SetLoaderDllFolderPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "desktop-runtime"));
        string profile = smoke == null
            ? Path.Combine(AppDomain.CurrentDomain.BaseDirectory, ".pdf-inspector-data", "desktop-profile") : smoke.ProfileDirectory;
        var options = new CoreWebView2EnvironmentOptions();
        options.Language = "zh-CN";
        CoreWebView2Environment environment;
        try
        {
            environment = await CoreWebView2Environment.CreateAsync(null, profile, options);
            await view.EnsureCoreWebView2Async(environment);
        }
        catch (WebView2RuntimeNotFoundException)
        { throw new InvalidOperationException("缺少 Microsoft Edge WebView2 运行时。请安装后重新打开资料库；已有资料仍保存在本机。"); }
        var settings = view.CoreWebView2.Settings;
        settings.IsStatusBarEnabled = false;
        settings.AreDevToolsEnabled = false;
        settings.AreBrowserAcceleratorKeysEnabled = false;
        settings.IsGeneralAutofillEnabled = false;
        settings.IsPasswordAutosaveEnabled = false;
        view.CoreWebView2.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e)
        { if (!IsLocalPage(e.Uri)) e.Cancel = true; };
        // Keep application content inside the desktop window, including links with target=_blank.
        view.CoreWebView2.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e)
        { e.Handled = true; if (IsLocalPage(e.Uri)) view.CoreWebView2.Navigate(e.Uri); };
        view.CoreWebView2.ProcessFailed += delegate { if (!closing) ShowFailure("界面加载中断。请点击“重新加载”；资料保存在本机。"); };
        if (smoke != null) smoke.Configure(view);
        initialized = true;
    }
    private async Task StartDesktop()
    {
        retry.Visible = false; reload.Enabled = false; timer.Stop();
        status.Text = "正在启动资料库…";
        message.Text = "正在检查本机环境并加载资料，请稍候…";
        message.Visible = true; message.BringToFront();
        Exception failure = null;
        try
        {
            await InitializeView();
            if (closing) return;
            if (runner != null) await Task.Run(() => runner.Stop());
            runner = new LocalRunner();
            await Task.Run(() => runner.StartServer(smoke == null ? null : smoke.DataDirectory));
            DateTime deadline = DateTime.UtcNow.AddSeconds(90);
            while (!runner.Ready)
            {
                if (closing) return;
                if (runner.Server.HasExited) throw new InvalidOperationException("资料库服务启动失败，请查看日志后重试。");
                if (DateTime.UtcNow > deadline) throw new TimeoutException("启动超时，请查看日志后重试。");
                await Task.Delay(250);
            }
            if (closing) return;
            await LoadPage();
            timer.Start();
            if (smoke != null) { await smoke.Run(view, runner); BeginInvoke(new Action(Close)); }
        }
        catch (Exception error)
        { failure = error; }
        if (failure != null)
        {
            if (smoke != null) smoke.Fail(failure);
            if (!closing)
            {
                ShowFailure(failure.Message);
                if (runner != null) await Task.Run(() => runner.Stop());
                retry.Visible = true;
                if (smoke != null) BeginInvoke(new Action(Close));
            }
        }
    }
    private async Task LoadPage()
    {
        reload.Enabled = false;
        await Task.Run(() => runner.VerifyPage());
        if (closing) return;
        var loaded = new TaskCompletionSource<bool>();
        EventHandler<CoreWebView2NavigationCompletedEventArgs> handler = delegate(object sender, CoreWebView2NavigationCompletedEventArgs e)
        {
            if (e.IsSuccess) loaded.TrySetResult(true);
            else loaded.TrySetException(new InvalidOperationException("界面加载失败：" + e.WebErrorStatus + "。请重新加载。"));
        };
        view.CoreWebView2.NavigationCompleted += handler;
        try
        {
            view.Visible = true;
            view.CoreWebView2.Navigate(runner.PageUrl);
            if (await Task.WhenAny(loaded.Task, Task.Delay(30000)) != loaded.Task)
                throw new TimeoutException("界面加载超时，请重新加载。");
            await loaded.Task;
            if (closing) return;
            message.Visible = false; view.BringToFront();
            status.Text = "本机资料库 · 资料自动保存，关闭后可继续使用";
            reload.Enabled = true;
        }
        finally { view.CoreWebView2.NavigationCompleted -= handler; }
    }
    private void ShowFailure(string text)
    {
        status.Text = "资料库暂时无法使用";
        message.Text = text; message.Visible = true; message.BringToFront();
        reload.Enabled = runner != null && runner.Ready && runner.Server != null && !runner.Server.HasExited;
    }
    private async void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (stopped) return;
        e.Cancel = true;
        if (closing) return;
        closing = true; timer.Stop(); reload.Enabled = false; retry.Enabled = false;
        status.Text = "正在停止服务并保存运行状态，请稍候…";
        try
        {
            if (startup != null) await startup;
            bool graceful = runner == null || await Task.Run(() => runner.Stop());
            if (smoke != null) smoke.Complete(graceful);
        }
        finally { view.Dispose(); timer.Dispose(); stopped = true; Close(); }
    }
}

internal static class Program
{
    [STAThread] private static int Main(string[] args)
    {
        using (var mutex = new Mutex(false, "Local\\PdfInspectorLauncher_" +
            Convert.ToBase64String(Encoding.UTF8.GetBytes(AppDomain.CurrentDomain.BaseDirectory)).Replace('\\', '_').Replace('/', '_')))
        {
            bool acquired;
            try { acquired = mutex.WaitOne(0); } catch (AbandonedMutexException) { acquired = true; }
            if (!acquired) { if (args.Length == 0) MessageBox.Show("资料库已经打开，请使用已有桌面窗口。", "PDF 资料库"); return 2; }
            try
            {
                if (args.Length == 3 && args[0] == "--smoke-report") return Smoke(args[1], args[2]);
                DesktopSmoke smoke = args.Length == 5 && args[0] == "--desktop-smoke-report"
                    ? new DesktopSmoke(args[1], args[2], args[3], args[4]) : null;
                if (args.Length != 0 && smoke == null) return 2;
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new LauncherForm(smoke));
                return smoke == null || smoke.Passed ? 0 : 1;
            }
            finally { mutex.ReleaseMutex(); }
        }
    }
    private static int Smoke(string reportPath, string dataDirectory)
    {
        var result = new Dictionary<string, object>();
        LocalRunner runner = null;
        int code = 1;
        try
        {
            runner = new LocalRunner();
            result["log"] = runner.LogPath;
            runner.StartServer(Path.GetFullPath(dataDirectory));
            DateTime deadline = DateTime.UtcNow.AddSeconds(90);
            while (!runner.Ready && DateTime.UtcNow < deadline)
            {
                if (runner.Server.HasExited) throw new InvalidOperationException("服务提前退出");
                Thread.Sleep(250);
            }
            if (!runner.Ready) throw new TimeoutException("启动超时");
            result["health"] = LocalRunner.Get("http://127.0.0.1:8000/health");
            string html = runner.VerifyPage();
            result["page_url"] = runner.PageUrl;
            result["no_store"] = true;
            result["demo"] = html.Contains("PDF 资料查询");
            result["empty_name"] = !html.Contains("value=\"资料查询\"") && html.Contains("placeholder=\"请输入知识库名称\"");
            result["upload_and_update"] = html.Contains("id=\"uploadTarget\"");
            result["saved_document_query"] = html.Contains("id=\"documentScope\"");
            result["delete_knowledge_base"] = html.Contains("id=\"deleteKb\"");
            result["ui_version"] = "2026.10.08.4";
            result["graceful_stop"] = runner.Stop();
            result["server_exit_code"] = runner.Server.ExitCode;
            if (!(bool)result["demo"] || !(bool)result["graceful_stop"] || runner.Server.ExitCode != 0)
                throw new InvalidOperationException("页面检查或正常停止失败");
            result["status"] = "passed"; code = 0;
        }
        catch (Exception error) { result["status"] = "failed"; result["error"] = error.Message; }
        finally
        {
            if (runner != null) runner.Dispose();
            File.WriteAllText(reportPath, new JavaScriptSerializer().Serialize(result), Encoding.UTF8);
        }
        return code;
    }
}
