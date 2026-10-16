param([long]$Hwnd,[int]$MaxNodes=300,[string]$Backend='auto',[string]$View='control',[int]$BudgetMs=5000)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$watch=[Diagnostics.Stopwatch]::StartNew()
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -Path @('C:\McpInbox\Desktop.cs','C:\McpInbox\Accessibility.cs') -ReferencedAssemblies System.dll,System.Core.dll,System.Drawing.dll,Accessibility.dll

function Managed-Tree {
    $root=[System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]$Hwnd)
    $walker=switch($View) {
        'raw' { [System.Windows.Automation.TreeWalker]::RawViewWalker }
        'content' { [System.Windows.Automation.TreeWalker]::ContentViewWalker }
        default { [System.Windows.Automation.TreeWalker]::ControlViewWalker }
    }
    $queue=New-Object 'System.Collections.Generic.Queue[object]'
    $nodes=New-Object 'System.Collections.Generic.List[object]'
    $queue.Enqueue(@{element=$root;parent=-1;depth=0})
    $characters=131072
    $truncated=$false
    while($queue.Count -and $nodes.Count -lt $MaxNodes -and $watch.ElapsedMilliseconds -lt $BudgetMs) {
        $item=$queue.Dequeue()
        try {
            $element=$item.element;$current=$element.Current;$rect=$current.BoundingRectangle
            $name=$current.Name
            if($current.IsPassword){$name=''}
            $name=$name.Substring(0,[Math]::Min($name.Length,[Math]::Min(1024,$characters)));$characters-=$name.Length
            $value=$null;$pattern=$null;$patterns=@()
            if(-not $current.IsPassword -and $element.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)) {
                $value=$pattern.Current.Value;$patterns+= 'Value'
            } elseif(-not $current.IsPassword -and $element.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern,[ref]$pattern)) {
                $value=$pattern.DocumentRange.GetText([Math]::Min(16384,$characters));$patterns+='Text'
            }
            if($null -ne $value){$value=$value.Substring(0,[Math]::Min($value.Length,[Math]::Min(16384,$characters)));$characters-=$value.Length}
            $index=$nodes.Count
            $nodes.Add(@{index=$index;parent=$item.parent;name=$name;automation_id=$current.AutomationId;
                type=$current.ControlType.ProgrammaticName;enabled=$current.IsEnabled;password=$current.IsPassword;
                value=$value;backend='uia2';patterns=$patterns;bounds=@{x=$rect.X;y=$rect.Y;width=$rect.Width;height=$rect.Height}})
            if($item.depth -ge 64){$truncated=$true;continue}
            $child=$walker.GetFirstChild($element)
            while($child){
                if($queue.Count+$nodes.Count -ge $MaxNodes -or $watch.ElapsedMilliseconds -ge $BudgetMs){$truncated=$true;break}
                $queue.Enqueue(@{element=$child;parent=$index;depth=$item.depth+1});$child=$walker.GetNextSibling($child)
            }
        } catch [System.Windows.Automation.ElementNotAvailableException] { }
    }
    return @{hwnd=$Hwnd;nodes=@($nodes.ToArray());backend='uia2';view=$View;truncated=($truncated -or $queue.Count -gt 0)}
}

$attempts=New-Object 'System.Collections.Generic.List[object]'
$best=$null;$bestScore=-1
$browserHost=[Desktop]::WindowClass($Hwnd) -match 'Chrome_WidgetWin|MozillaWindowClass'
$choices=if($Backend -eq 'auto'){@('uia3','ia2','win32')}else{@($Backend)}
foreach($choice in $choices) {
    if($watch.ElapsedMilliseconds -ge $BudgetMs){break}
    try {
        $remaining=[Math]::Max(100,$BudgetMs-$watch.ElapsedMilliseconds)
        $result=switch($choice) {
            'uia3' {[NativeAccessibility]::Uia($Hwnd,$MaxNodes,$remaining,$View)}
            'ia2' {[NativeAccessibility]::Ia2($Hwnd,$MaxNodes,$remaining)}
            'uia2' {Managed-Tree}
            'win32' {@{hwnd=$Hwnd;nodes=@([Desktop]::Controls($Hwnd,$MaxNodes).ToArray());backend='win32';view='raw';truncated=$false}}
            default {throw 'Unsupported accessibility backend'}
        }
        $semantic=@($result.nodes | Where-Object {$_.type -in @('ControlType.Edit','ControlType.Button','ControlType.Hyperlink','ControlType.ComboBox','ControlType.CheckBox','ControlType.RadioButton','ControlType.ListItem','ControlType.TabItem')}).Count
        $score=$semantic*10000+$result.nodes.Count
        $attempts.Add(@{backend=$choice;nodes=$result.nodes.Count;actionable_nodes=$semantic;ok=$true})
        if($score -gt $bestScore){$best=$result;$bestScore=$score}
        if($Backend -eq 'auto' -and $semantic -ge 2 -and (-not $browserHost -or $choice -eq 'ia2')){break}
    } catch {
        $attempts.Add(@{backend=$choice;ok=$false;error=$_.Exception.Message.Substring(0,[Math]::Min(512,$_.Exception.Message.Length))})
        if($Backend -ne 'auto'){throw}
    }
}
if($null -eq $best){throw 'No accessibility backend completed within its budget'}
$best['attempts']=@($attempts.ToArray());$best['duration_ms']=$watch.ElapsedMilliseconds
$best['truncated']=[bool]$best.truncated -or $watch.ElapsedMilliseconds -ge $BudgetMs
ConvertTo-Json -InputObject $best -Depth 15 -Compress
