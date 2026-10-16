param([Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{32}$')][string]$Session)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$inbox = 'C:\McpInbox'
$outbox = 'C:\McpOutbox'
New-Item -ItemType Directory -Force -Path 'C:\work' | Out-Null
Set-Location -LiteralPath 'C:\work'
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -Path "$inbox\Desktop.cs" -ReferencedAssemblies System.dll,System.Core.dll,System.Drawing.dll
Add-Type -Path "$inbox\Accessibility.cs" -ReferencedAssemblies System.dll,System.Core.dll,Accessibility.dll
$seen = New-Object 'System.Collections.Generic.HashSet[string]'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$env:WSMCP_AGENT_PID=$PID
$debugPorts=New-Object 'System.Collections.Generic.HashSet[int]'

function Work-Path([string]$Path) {
    if ($Path -notmatch '^C:\\work\\' -or $Path.IndexOf(':', 2) -ge 0) { throw 'Path must be under C:\work' }
    $full = [IO.Path]::GetFullPath($Path)
    if (-not $full.StartsWith('C:\work\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path traversal rejected' }
    $part = $full
    while ($part -and $part -ne 'C:\') {
        if (Test-Path -LiteralPath $part) {
            if ((Get-Item -LiteralPath $part -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse path rejected' }
        }
        $part = [IO.Path]::GetDirectoryName($part)
    }
    return $full
}

function Inspect-Window([long]$Hwnd,[int]$MaxNodes,[string]$Backend='auto',[string]$View='control',[int]$TimeoutMs=8000) {
    if($MaxNodes -lt 1 -or $MaxNodes -gt 1000 -or $TimeoutMs -lt 2000 -or $TimeoutMs -gt 20000){throw 'Invalid inspection budget'}
    if($Backend -notin @('auto','uia3','uia2','ia2','win32') -or $View -notin @('raw','control','content')){throw 'Invalid inspection backend/view'}
    if($Hwnd -eq 0){$Hwnd=[Desktop]::GetForegroundWindow().ToInt64()}
    $command="& 'C:\McpInbox\inspect.ps1' -Hwnd $Hwnd -MaxNodes $MaxNodes -Backend $Backend -View $View -BudgetMs $($TimeoutMs-1000)"
    $output=[GuestCommand]::Run($command,$TimeoutMs,2097152)
    if($output['timed_out']){throw 'INSPECTION_TIMEOUT: accessibility worker terminated; guest remains usable'}
    if($output['possibly_truncated']){throw 'INSPECTION_OUTPUT_LIMIT: reduce max_nodes'}
    if($output['exit_code'] -ne 0){throw ('INSPECTION_FAILED: '+$output['stderr'])}
    return ($output['stdout'] | ConvertFrom-Json)
}
function Invoke-Operation($Request) {
    $p = $Request.params
    switch ($Request.op) {
        'ping' { return @{ ready=$true; runtime=$PSVersionTable.PSVersion.ToString(); computer=$env:COMPUTERNAME } }
        'exec' {
            if ($p.command.Length -lt 1 -or $p.command.Length -gt 65536 -or $p.timeout_ms -lt 100 -or $p.timeout_ms -gt 300000) { throw 'Invalid command arguments' }
            return [GuestCommand]::Run([string]$p.command,[int]$p.timeout_ms)
        }
        'launch' {
            if ([string]::IsNullOrWhiteSpace($p.executable) -or $p.executable.Length -gt 1024 -or $p.executable.Contains([char]0) -or $p.executable.Contains('"')) { throw 'Invalid executable' }
            $cwd='C:\work'
            if ([IO.Path]::IsPathRooted($p.executable)) { $cwd=[IO.Path]::GetDirectoryName($p.executable) }
            $arguments=New-Object 'System.Collections.Generic.List[string]'
            foreach($argument in @($p.arguments)){if($null -ne $argument){$arguments.Add([string]$argument)}}
            if($p.accessibility){$arguments.Add('--force-renderer-accessibility')}
            if($p.cdp_port -gt 0){$arguments.Add('--remote-debugging-address=127.0.0.1');$arguments.Add("--remote-debugging-port=$($p.cdp_port)")}
            $info=New-Object Diagnostics.ProcessStartInfo
            $info.FileName=$p.executable;$info.WorkingDirectory=$cwd;$info.UseShellExecute=$false
            $info.Arguments=(@($arguments | ForEach-Object {[NativeAccessibility]::Quote($_)}) -join ' ')
            if($info.Arguments.Length -gt 30000){throw 'Launch arguments exceed Windows limit'}
            $process=[Diagnostics.Process]::Start($info)
            if($p.cdp_port -gt 0){[void]$debugPorts.Add([int]$p.cdp_port)}
            return @{pid=$process.Id;accessibility=[bool]$p.accessibility;cdp_port=[int]$p.cdp_port}
        }
        'browser' {
            if(-not $debugPorts.Contains([int]$p.port)){throw 'CDP_NOT_ENABLED: launch with an explicit cdp_port first'}
            if($p.action -notin @('snapshot','click','fill') -or $p.target_id -notmatch '^[a-zA-Z0-9_-]{0,128}$' -or $p.reference -notmatch '^[a-zA-Z0-9:]{0,64}$'){throw 'Invalid browser arguments'}
            $encoded=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes([string]$p.text))
            $command="& 'C:\McpInbox\browser.ps1' -Port $([int]$p.port) -Action '$($p.action)' -TargetId '$($p.target_id)' -Reference '$($p.reference)' -TextBase64 '$encoded'"
            $output=[GuestCommand]::Run($command,12000,2097152)
            if($output['timed_out']){throw 'CDP_TIMEOUT: browser worker terminated; guest remains usable'}
            if($output['possibly_truncated']){throw 'CDP_OUTPUT_LIMIT'}
            if($output['exit_code'] -ne 0){throw ('CDP_FAILED: '+$output['stderr'])}
            return ($output['stdout'] | ConvertFrom-Json)
        }
        'upload' {
            $path = Work-Path $p.path
            if ($p.data.Length -gt 5592408) { throw 'File exceeds limit' }
            $bytes = [Convert]::FromBase64String($p.data)
            if ($bytes.Length -gt 4194304) { throw 'File exceeds limit' }
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path)) | Out-Null
            [IO.File]::WriteAllBytes($path,$bytes)
            return @{ path=$path; size=$bytes.Length }
        }
        'download' {
            $path = Work-Path $p.path
            $stream = [IO.File]::OpenRead($path)
            try {
                if ($stream.Length -gt 4194304) { throw 'File exceeds limit' }
                $buffer = New-Object byte[] 4194305
                $offset=0
                while ($offset -lt $buffer.Length) {
                    $read=$stream.Read($buffer,$offset,$buffer.Length-$offset)
                    if ($read -eq 0) { break }; $offset+=$read
                }
                if ($offset -gt 4194304) { throw 'File exceeds limit' }
                return @{ data=[Convert]::ToBase64String($buffer,0,$offset); size=$offset }
            } finally { $stream.Dispose() }
        }
        'screenshot' { return @{ data=[Convert]::ToBase64String([Desktop]::Screenshot()) } }
        'windows' { return @{ windows=@([Desktop]::Windows().ToArray()) } }
        'inspect' {
            $backend=if($p.backend){$p.backend}else{'auto'}
            $view=if($p.view){$p.view}else{'control'}
            $timeout=if($p.timeout_ms){[int]$p.timeout_ms}else{8000}
            return Inspect-Window ([long]$p.hwnd) ([int]$p.max_nodes) $backend $view $timeout
        }
        'click' {
            if ($p.button -notin @('left','right')) { throw 'Invalid mouse button' }
            [Desktop]::Focus([long]$p.hwnd); [Desktop]::Click([int]$p.x,[int]$p.y,$p.button)
            return @{ applied=$true; foreground=[Desktop]::GetForegroundWindow().ToInt64() }
        }
        'text' { [Desktop]::Focus([long]$p.hwnd); [Desktop]::Text([string]$p.text); return @{ applied=$true } }
        'keys' { [Desktop]::Focus([long]$p.hwnd); [Desktop]::Keys([string]$p.chord); return @{ applied=$true } }
        'shutdown' { Start-Process shutdown.exe -ArgumentList '/s /t 0'; return @{ stopping=$true } }
        default { throw 'Unknown operation' }
    }
}

while ($true) {
    # Enumerate names only: mapped folders can retain hundreds of old request
    # files, and PowerShell FileInfo construction adds remote metadata lookups.
    foreach ($marker in [IO.Directory]::GetFiles($inbox,'*.ready')) {
        $id = [IO.Path]::GetFileNameWithoutExtension($marker)
        if ($id -notmatch '^[0-9a-f]{32}$' -or $seen.Contains($id)) { continue }
        [void]$seen.Add($id)
        $response = @{ v=1; session=$Session; id=$id; ok=$false; result=$null; error=$null }
        try {
            $file = Get-Item -LiteralPath "$inbox\$id.request.json"
            if ($file.Length -gt 6291456) { throw 'Request exceeds limit' }
            $request = [IO.File]::ReadAllText($file.FullName,$utf8) | ConvertFrom-Json
            if ($request.v -ne 1 -or $request.session -ne $Session -or $request.id -ne $id) { throw 'Request identity mismatch' }
            $env:WSMCP_ACTIVE_REQUEST=$id
            $response.result = Invoke-Operation $request
            $response.ok = $true
        } catch {
            $message = $_.Exception.Message
            if ($message.Length -gt 4096) { $message = $message.Substring(0,4096) }
            $code='OPERATION_FAILED'
            if($message -match '^([A-Z_]{3,40}):'){$code=$Matches[1]}
            $response.error = @{ code=$code; message=$message }
            $response.result=$null
        }
        $json = ConvertTo-Json -InputObject $response -Depth 20 -Compress
        if ($utf8.GetByteCount($json) -gt 6291456) {
            $response.ok=$false; $response.result=$null
            $response.error=@{code='PAYLOAD_TOO_LARGE';message='Response exceeds limit'}
            $json=ConvertTo-Json -InputObject $response -Compress
        }
        $temporary = "$outbox\$id.tmp"
        [IO.File]::WriteAllText($temporary,$json,$utf8)
        [IO.File]::Move($temporary,"$outbox\$id.response.json")
    }
    Start-Sleep -Milliseconds 100
}
