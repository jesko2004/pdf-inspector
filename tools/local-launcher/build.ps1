$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) {
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'
}
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Windows .NET Framework compiler is unavailable.' }
$source = Join-Path $PSScriptRoot 'Launcher.cs'
$destination = Join-Path $projectRoot 'PDF资料库.exe'
$sdkVersion = '1.0.4258.31'
$sdk = Join-Path $projectRoot ".codex-tools/webview2/$sdkVersion"
$archive = Join-Path $sdk 'sdk.zip'
$expectedHash = '56F7F4B8BF9AEE4B8EFEFBBDD4F67D5F74EBD1B100ED0806DA71BF76AF481AA9'
New-Item -ItemType Directory -Path $sdk -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest -UseBasicParsing "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$sdkVersion/microsoft.web.webview2.$sdkVersion.nupkg" -OutFile $archive
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expectedHash) { throw 'WebView2 SDK checksum mismatch.' }
Expand-Archive -LiteralPath $archive -DestinationPath $sdk -Force
$runtime = Join-Path $projectRoot 'desktop-runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
foreach ($assembly in @('Microsoft.Web.WebView2.Core.dll', 'Microsoft.Web.WebView2.WinForms.dll')) {
    Copy-Item -LiteralPath (Join-Path $sdk "lib/net462/$assembly") -Destination $runtime -Force
}
Copy-Item -LiteralPath (Join-Path $sdk 'runtimes/win-x64/native/WebView2Loader.dll') -Destination $runtime -Force
Copy-Item -LiteralPath (Join-Path $sdk 'LICENSE.txt') -Destination (Join-Path $runtime 'WebView2-LICENSE.txt') -Force
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'app.config') -Destination "$destination.config" -Force
$smokeSource = Join-Path $PSScriptRoot 'DesktopSmoke.cs'
& $compiler /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 "/out:$destination" /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/reference:$runtime/Microsoft.Web.WebView2.Core.dll" "/reference:$runtime/Microsoft.Web.WebView2.WinForms.dll" $source $smokeSource
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Get-Item -LiteralPath $destination | Select-Object FullName, Length
