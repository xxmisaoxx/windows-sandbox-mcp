param([int]$Port,[string]$Action='snapshot',[string]$TargetId='',[string]$Reference='',[string]$TextBase64='')
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
Add-Type -Path 'C:\McpInbox\Cdp.cs' -ReferencedAssemblies System.dll,System.Core.dll,System.Web.Extensions.dll
$text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextBase64))
$result=[GuestCdp]::Run($Port,$TargetId,$Action,$Reference,$text)
ConvertTo-Json -InputObject $result -Depth 15 -Compress
