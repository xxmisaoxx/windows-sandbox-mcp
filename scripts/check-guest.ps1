$ErrorActionPreference='Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Run this check with Windows PowerShell 5.1' }
$project = Split-Path -Parent $PSScriptRoot
$errors=$null; $tokens=$null
foreach($script in @('agent.ps1','inspect.ps1','browser.ps1')) {
    [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $project ('src\winsandbox_mcp\guest\'+$script)),[ref]$tokens,[ref]$errors) | Out-Null
    if ($errors.Count) { throw ($errors | Out-String) }
}
Add-Type -Path (Join-Path $project 'src\winsandbox_mcp\guest\Desktop.cs') -ReferencedAssemblies System.dll,System.Core.dll,System.Drawing.dll
Add-Type -Path (Join-Path $project 'src\winsandbox_mcp\guest\Accessibility.cs') -ReferencedAssemblies System.dll,System.Core.dll,Accessibility.dll
Add-Type -Path (Join-Path $project 'src\winsandbox_mcp\guest\Cdp.cs') -ReferencedAssemblies System.dll,System.Core.dll,System.Web.Extensions.dll
Write-Output ('Guest helper compiled; agent parsed on PowerShell ' + $PSVersionTable.PSVersion)
