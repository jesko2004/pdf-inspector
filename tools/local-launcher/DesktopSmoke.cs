using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// Opt-in executable acceptance mode. All mutations use explicitly supplied test directories.
internal sealed class DesktopSmoke
{
    public readonly string DataDirectory, ProfileDirectory;
    private readonly string reportPath, phase;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();
    private readonly Dictionary<string, object> result = new Dictionary<string, object>();
    private bool completed;
    public bool Passed { get; private set; }
    public DesktopSmoke(string report, string data, string profile, string testPhase)
    {
        reportPath = Path.GetFullPath(report);
        DataDirectory = Path.GetFullPath(data);
        ProfileDirectory = Path.GetFullPath(profile);
        phase = testPhase;
        string testRoot = Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "tmp")) + Path.DirectorySeparatorChar;
        if (!DataDirectory.StartsWith(testRoot, StringComparison.OrdinalIgnoreCase) ||
            !ProfileDirectory.StartsWith(testRoot, StringComparison.OrdinalIgnoreCase) ||
            !reportPath.StartsWith(testRoot, StringComparison.OrdinalIgnoreCase) ||
            (phase != "create" && phase != "reopen" && phase != "delete" && phase != "empty"))
            throw new ArgumentException("桌面验收仅允许使用项目 tmp 下的独立测试数据和配置目录。");
        result["phase"] = phase;
        result["ui_version"] = "2026.10.08.4";
    }
    public void Configure(WebView2 view)
    {
        view.CoreWebView2.Settings.AreDefaultScriptDialogsEnabled = false;
        view.CoreWebView2.ScriptDialogOpening += delegate(object sender, CoreWebView2ScriptDialogOpeningEventArgs e)
        {
            result["confirmation"] = e.Message;
            if (phase == "delete" && e.Kind == CoreWebView2ScriptDialogKind.Confirm &&
                (e.Message.Contains("桌面验收") || e.Message.Contains("我的资料"))) e.Accept();
        };
    }
    private async Task Check(WebView2 view, string expression, string name)
    {
        if (await view.ExecuteScriptAsync("Boolean(" + expression + ")") != "true")
            throw new InvalidOperationException("桌面验收失败：" + name + "; " + await view.ExecuteScriptAsync("document.getElementById('error').textContent"));
        result[name] = true;
    }
    private async Task Wait(WebView2 view, string expression)
    {
        DateTime deadline = DateTime.UtcNow.AddSeconds(120);
        while (await view.ExecuteScriptAsync("Boolean(" + expression + ")") != "true")
        {
            if (DateTime.UtcNow > deadline)
                throw new TimeoutException("等待界面操作超时：" + expression + "; " + await view.ExecuteScriptAsync("document.body.innerText"));
            await Task.Delay(250);
        }
    }
    public async Task Run(WebView2 view, LocalRunner runner)
    {
        result["log"] = runner.LogPath;
        result["profile"] = view.CoreWebView2.Environment.UserDataFolder;
        await Wait(view, "!document.getElementById('connect').disabled && (document.getElementById('kb').value || document.getElementById('libraryStatus').textContent.includes('还没有知识库'))");
        await Check(view, "document.querySelector('meta[name=pdf-inspector-ui-version]').content === '2026.10.08.4'", "current_interface");
        await Check(view, "document.getElementById('name').value === ''", "blank_new_name");
        await Check(view, "typeof window.crypto.subtle.digest === 'function'", "secure_file_hashing");
        await Check(view, "typeof window.confirm === 'function' && typeof DataTransfer === 'function'", "native_dialog_and_file_support");
        await Check(view, "Array.from(document.getElementById('mode').options,o=>o.value).join(',') === 'hybrid,bm25,vector'", "retrieval_options");
        if (phase == "create")
        {
            await view.ExecuteScriptAsync("document.getElementById('name').value='桌面验收';document.getElementById('name').dispatchEvent(new Event('input'));document.getElementById('create').click();");
            await Wait(view, "document.getElementById('kb').selectedOptions[0].textContent.startsWith('桌面验收') && document.getElementById('name').value==='' && !creating");
            await view.ExecuteScriptAsync("localStorage.setItem('desktop-smoke.expected', document.getElementById('kb').value)");
            await Upload(view, "bare_name_struct.pdf", "桌面简历.pdf");
            await Wait(view, "document.getElementById('progress').textContent.includes('已保存') && !uploading");
            await Check(view, "currentDocuments.length === 1 && currentDocuments[0].status === 'ready'", "document_saved");
            await view.ExecuteScriptAsync("localStorage.setItem('desktop-smoke.document', currentDocuments[0].id)");
            result["knowledge_base"] = await view.ExecuteScriptAsync("document.getElementById('kb').value");
        }
        else if (phase == "reopen")
        {
            await Check(view, "document.getElementById('kb').value === localStorage.getItem('desktop-smoke.expected')", "selection_restored");
            await Wait(view, "currentDocuments.length === 1");
            await Check(view, "currentDocuments[0].id === localStorage.getItem('desktop-smoke.document') && currentDocuments[0].filename === '桌面简历.pdf'", "document_restored");
            await view.ExecuteScriptAsync("document.getElementById('uploadTarget').value=currentDocuments[0].id;document.getElementById('uploadTarget').dispatchEvent(new Event('change'));");
            await Upload(view, "thermo-freon12.pdf", "新版桌面简历.pdf");
            await Wait(view, "!uploading && document.getElementById('progress').textContent.includes('已更新并保存') && currentDocuments[0].filename === '新版桌面简历.pdf'");
            await Check(view, "currentDocuments.length === 1 && currentDocuments[0].id === localStorage.getItem('desktop-smoke.document')", "in_place_update");
            await view.ExecuteScriptAsync("document.getElementById('documentScope').value=currentDocuments[0].id;document.getElementById('mode').value='bm25';document.getElementById('question').value='freon';document.getElementById('ask').click();");
            await Wait(view, "!document.getElementById('ask').disabled");
            await Check(view, "lastAnswer !== null && !document.getElementById('error').textContent", "saved_document_query");
        }
        else if (phase == "delete")
        {
            await Wait(view, "currentDocuments.length === 1");
            await Check(view, "currentDocuments[0].filename === '新版桌面简历.pdf'", "updated_file_survives_restart");
            await view.ExecuteScriptAsync("document.getElementById('deleteKb').click()");
            await Wait(view, "document.getElementById('kb').value !== localStorage.getItem('desktop-smoke.expected') && !document.getElementById('deleteKb').disabled");
            await Check(view, "!Array.from(document.getElementById('kb').options).some(o=>o.value===localStorage.getItem('desktop-smoke.expected'))", "delete_selected_base");
            await view.ExecuteScriptAsync("document.getElementById('deleteKb').click()");
            await Wait(view, "!document.getElementById('kb').value && !deleting");
            await Check(view, "localStorage.getItem('pdf-inspector.suppressDefaultKnowledgeBase') === '1'", "last_delete_stays_empty");
        }
        else await Check(view, "!document.getElementById('kb').value && knowledgeBases.length === 0", "empty_state_survives_restart");
        using (var output = File.Create(Path.ChangeExtension(reportPath, ".png")))
            await view.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, output);
        result["embedded_window"] = true;
        result["status"] = "passed";
        Passed = true;
    }
    private async Task Upload(WebView2 view, string fixture, string filename)
    {
        byte[] pdf = File.ReadAllBytes(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "tests", "fixtures", fixture));
        string script = "(()=>{const bytes=Uint8Array.from(atob(" + json.Serialize(Convert.ToBase64String(pdf)) + "),c=>c.charCodeAt(0));const transfer=new DataTransfer();transfer.items.add(new File([bytes]," + json.Serialize(filename) + ",{type:'application/pdf'}));document.getElementById('file').files=transfer.files;document.getElementById('file').dispatchEvent(new Event('change'));document.getElementById('upload').click();})()";
        await view.ExecuteScriptAsync(script);
    }
    public void Fail(Exception error)
    { Passed = false; result["status"] = "failed"; result["error"] = error.ToString(); }
    public void Complete(bool graceful)
    {
        if (completed) return;
        completed = true;
        result["graceful_stop"] = graceful;
        if (!graceful || !Passed) { Passed = false; result["status"] = "failed"; }
        File.WriteAllText(reportPath, json.Serialize(result), Encoding.UTF8);
    }
}
