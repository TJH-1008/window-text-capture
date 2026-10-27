param(
    [ValidateSet('list','capture')][string]$Mode='list',
    [long]$WindowHandle=0,
    [string]$SaveDirectory='',
    [string]$StopFile='',
    [switch]$AutoScroll,
    [switch]$FinalOnly,
    [ValidateSet('mall','general')][string]$CaptureProfile='mall',
    [ValidateSet('down','up')][string]$ScrollDirection='down',
    [int]$MaximumSteps=120,
    [int]$WaitMilliseconds=1200
)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$OutputEncoding=[Console]::OutputEncoding
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -AssemblyName Accessibility
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class WindowCaptureNative {
 public delegate bool EnumProc(IntPtr h,IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb,IntPtr p);
 [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h,EnumProc cb,IntPtr p);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h,StringBuilder s,int n);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint id);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
 [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r);
 [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h,IntPtr dc,uint flags);
 [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags,uint x,uint y,int data,UIntPtr info);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll")] public static extern IntPtr SendMessageTimeout(IntPtr h,uint m,IntPtr w,IntPtr l,uint flags,uint timeout,out IntPtr r);
 [DllImport("oleacc.dll")] public static extern int AccessibleObjectFromWindow(IntPtr h,uint id,ref Guid iid,[MarshalAs(UnmanagedType.Interface)] out object obj);
 [DllImport("oleacc.dll")] public static extern int AccessibleChildren([MarshalAs(UnmanagedType.Interface)] object p,int start,int count,[Out,MarshalAs(UnmanagedType.LPArray,SizeParamIndex=2)] object[] kids,out int got);
 public struct RECT {public int L,T,R,B;}
 public struct POINT {public int X,Y;}
}
"@

function Emit($kind,$data) {
    [Console]::WriteLine((@{kind=$kind;data=$data}|ConvertTo-Json -Compress -Depth 8))
}
function Stopped {
    if($StopFile -and (Test-Path -LiteralPath $StopFile)){return $true}
    return ([WindowCaptureNative]::GetAsyncKeyState(0x1B) -lt 0)
}
function WindowTitle([IntPtr]$handle) {
    $text=New-Object Text.StringBuilder 2048
    [void][WindowCaptureNative]::GetWindowText($handle,$text,2048)
    return $text.ToString()
}
function ReadDocuments([IntPtr]$handle,[switch]$AllowStopped) {
    if(-not [WindowCaptureNative]::IsWindow($handle)){throw '所选窗口已关闭，请刷新窗口列表'}
    $root=[System.Windows.Automation.AutomationElement]::FromHandle($handle)
    $condition=New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ControlTypeProperty),([System.Windows.Automation.ControlType]::Document)
    $found=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    $documents=New-Object System.Collections.Generic.List[object]
    foreach($doc in $found){
        if(-not $AllowStopped -and (Stopped)){break}
        $text='';$errorText=''
        try{$text=($doc.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)).DocumentRange.GetText(-1)}catch{$errorText=$_.Exception.Message}
        $documents.Add([pscustomobject]@{name=$doc.Current.Name;offscreen=$doc.Current.IsOffscreen;text=$text;length=$text.Length;error=$errorText})
    }
    return ,$documents.ToArray()
}
function ReadCurrentText([IntPtr]$handle) {
    if(-not [WindowCaptureNative]::IsWindow($handle)){throw '所选窗口已关闭'}
    $root=[System.Windows.Automation.AutomationElement]::FromHandle($handle)
    $condition=New-Object System.Windows.Automation.PropertyCondition ([System.Windows.Automation.AutomationElement]::ControlTypeProperty),([System.Windows.Automation.ControlType]::Document)
    $found=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,$condition)
    for($i=$found.Count-1;$i -ge 0;$i--){
        if(Stopped){return ''}
        try{$text=($found[$i].GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)).DocumentRange.GetText(-1)}catch{continue}
        if($text){return $text}
    }
    return ''
}
function EnableAccessibility([IntPtr]$handle) {
    Emit 'progress' '初始化窗口文本兼容接口…'
    $handles=New-Object System.Collections.Generic.List[IntPtr]
    $handles.Add($handle)
    $callback=[WindowCaptureNative+EnumProc]{param($h,$p) $handles.Add($h);return $true}
    [void][WindowCaptureNative]::EnumChildWindows($handle,$callback,[IntPtr]::Zero)
    foreach($item in $handles){
        if(Stopped){return}
        $class=New-Object Text.StringBuilder 256
        [void][WindowCaptureNative]::GetClassName($item,$class,256)
        if($class.ToString() -notmatch 'Chrome|Widget|WebView'){continue}
        $guid=[Guid]'618736E0-3C3D-11CF-810C-00AA00389B71';$acc=$null
        [void][WindowCaptureNative]::AccessibleObjectFromWindow($item,[uint32]4294967292,[ref]$guid,[ref]$acc)
        $result=[IntPtr]::Zero
        [void][WindowCaptureNative]::SendMessageTimeout($item,0x003D,[IntPtr]::Zero,[IntPtr](-4),2,1200,[ref]$result)
        [void][WindowCaptureNative]::SendMessageTimeout($item,0x003D,[IntPtr]::Zero,[IntPtr]1,2,1200,[ref]$result)
        if($acc){
            $stack=New-Object System.Collections.Stack
            $stack.Push($acc);$clock=[Diagnostics.Stopwatch]::StartNew();$visits=0
            while($stack.Count -and $clock.Elapsed.TotalSeconds -lt 18 -and $visits -lt 1800){
                if(Stopped){return}
                $node=$stack.Pop();$visits++
                try{
                    $count=$node.accChildCount
                    if($count -gt 0 -and $count -lt 20000){
                        $kids=New-Object object[] $count;$got=0
                        [void][WindowCaptureNative]::AccessibleChildren($node,0,$count,$kids,[ref]$got)
                        for($i=$got-1;$i -ge 0;$i--){if($kids[$i] -and $kids[$i] -isnot [int]){$stack.Push($kids[$i])}}
                    }
                }catch{}
            }
        }
    }
}
function SaveSnapshot([IntPtr]$handle,[int]$step,$documents) {
    $primary=-1
    for($i=0;$i -lt $documents.Count;$i++){if($documents[$i].text){$primary=$i}}
    $bottom=$false
    if($primary -ge 0){$bottom=$documents[$primary].text -match '已经到底|没有更多了|暂无更多|已显示全部'}
    $payload=[ordered]@{captured_at=[DateTimeOffset]::Now.ToString('o');window_title=(WindowTitle $handle);window_handle=[long]$handle;step=$step;primary_document_index=$primary;bottom_confirmed=$bottom;documents=@($documents)}
    $file=Join-Path $SaveDirectory ('raw-{0:D4}.json' -f $step)
    $payload|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $file -Encoding UTF8
    Emit 'snapshot' @{file=$file;step=$step;bottom_confirmed=$bottom;characters=(@($documents|ForEach-Object {$_.length})|Measure-Object -Sum).Sum}
    return $payload
}
function Invoke-FinalScroll($Probe,$Scroll,$Wait,$Stop,$Focus,$Progress,[int]$MaximumSteps) {
    $previous='';$stable=0;$bottomStable=$false;$steps=0;$bottomChecks=0
    $reason='达到滚动步数上限；底部状态未确认'
    if(& $Stop){return @{steps=0;bottom_stable=$false;reason='用户停止';last_text=''}}
    if(-not (& $Focus)){return @{steps=0;bottom_stable=$false;reason='目标窗口失去焦点';last_text=''}}
    $previous=[string](& $Probe)
    while($true){
        if(& $Stop){$reason='用户停止，已保留可读文本';break}
        if(-not (& $Focus)){$reason='目标窗口失去焦点，已停止滚动';break}
        if(-not $previous){$reason='当前列表文本暂不可读，底部状态未确认';break}
        $bottom=$previous -match '已经到底|没有更多了|暂无更多|已显示全部'
        if($bottom){
            if($bottomChecks -ge 8){$reason='底部文本持续变化，内容稳定状态未确认';break}
            $bottomChecks++
            & $Progress '已检测到底部提示，等待列表文本稳定…'
        }else{
            if($steps -ge $MaximumSteps){break}
            & $Scroll
            $steps++
            & $Progress ("快速滚动第 $steps 步；只检查当前列表，不保存中间快照。")
        }
        & $Wait
        if(& $Stop){$reason='用户停止，已保留可读文本';break}
        if(-not (& $Focus)){$reason='目标窗口失去焦点，已停止滚动';break}
        $text=[string](& $Probe)
        if($text -ceq $previous){$stable++}else{$stable=0}
        $previous=$text
        if($bottom -and $text -match '已经到底|没有更多了|暂无更多|已显示全部' -and $stable -ge 2){
            $bottomStable=$true;$reason='检测到底部提示且文本连续两次稳定';break
        }
        if(-not $bottom -and $stable -ge 5){$reason='连续5次文本不变；底部状态未确认';break}
    }
    return @{steps=$steps;bottom_stable=$bottomStable;reason=$reason;last_text=$previous}
}
function SaveScreenshot([IntPtr]$handle) {
    $rect=New-Object WindowCaptureNative+RECT
    [void][WindowCaptureNative]::GetWindowRect($handle,[ref]$rect)
    $width=$rect.R-$rect.L;$height=$rect.B-$rect.T
    if($width -lt 1 -or $height -lt 1 -or $width -gt 12000 -or $height -gt 12000){return}
    $bitmap=New-Object Drawing.Bitmap $width,$height
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    try{
        $dc=$graphics.GetHdc()
        try{$ok=[WindowCaptureNative]::PrintWindow($handle,$dc,2)}finally{$graphics.ReleaseHdc($dc)}
        if($ok){$bitmap.Save((Join-Path $SaveDirectory '窗口截图.png'),[Drawing.Imaging.ImageFormat]::Png)}
    }finally{$graphics.Dispose();$bitmap.Dispose()}
}

try {
    if($Mode -eq 'list'){
        $windows=New-Object System.Collections.Generic.List[object]
        $callback=[WindowCaptureNative+EnumProc]{param($h,$p)
            if([WindowCaptureNative]::IsWindowVisible($h)){
                $title=WindowTitle $h
                if($title){
                    $processId=[uint32]0;[void][WindowCaptureNative]::GetWindowThreadProcessId($h,[ref]$processId)
                    $processName='';try{$processName=(Get-Process -Id $processId).ProcessName}catch{}
                    $windows.Add([pscustomobject]@{handle=[long]$h;title=$title;process=$processName;pid=$processId})
                }
            };return $true
        }
        [void][WindowCaptureNative]::EnumWindows($callback,[IntPtr]::Zero)
        Emit 'windows' @($windows.ToArray())
        exit 0
    }
    if(-not $WindowHandle -or -not $SaveDirectory){throw '缺少窗口或保存目录'}
    [void](New-Item -ItemType Directory -Path $SaveDirectory -Force)
    $handle=[IntPtr]$WindowHandle
    if($CaptureProfile -eq 'general'){
        . (Join-Path $PSScriptRoot 'generic_reader.ps1')
        Invoke-GenericCapture $handle
        exit 0
    }
    $reason='单次读取';$current=$null;$finalOnlyMode=($AutoScroll -and $FinalOnly)
    $stable=0
    $documents=ReadDocuments $handle
    if(-not @($documents|Where-Object {$_.text}).Count -and -not(Stopped)){
        EnableAccessibility $handle
        $documents=ReadDocuments $handle
    }
    if(-not @($documents|Where-Object {$_.text}).Count){
        if(Stopped){throw '已停止；本次未取得可访问性文本'}
        throw '窗口未提供可读取的文档文本。请确认已打开商户列表；图片或画布页面可能无法直接读取。'
    }
    if(-not $finalOnlyMode){$current=SaveSnapshot $handle 0 $documents}
    $previous=($documents|ConvertTo-Json -Compress -Depth 6)
    if($AutoScroll -and $finalOnlyMode){
        if([WindowCaptureNative]::IsIconic($handle)){[void][WindowCaptureNative]::ShowWindow($handle,9)}
        [void][WindowCaptureNative]::SetForegroundWindow($handle)
        Start-Sleep -Milliseconds 350
        if([WindowCaptureNative]::GetForegroundWindow() -ne $handle){throw '无法激活目标窗口；快速采集未读取页面文本。'}
        Emit 'progress' '快速模式：滚动时检查列表是否稳定，不保存中间快照；请保持目标窗口在前台。'
        $rect=New-Object WindowCaptureNative+RECT;[void][WindowCaptureNative]::GetWindowRect($handle,[ref]$rect)
        $cursor=New-Object WindowCaptureNative+POINT;[void][WindowCaptureNative]::GetCursorPos([ref]$cursor)
        $scroll={
            if([WindowCaptureNative]::GetForegroundWindow() -ne $handle){return}
            [void][WindowCaptureNative]::SetCursorPos([int](($rect.L+$rect.R)/2),[int]($rect.T+($rect.B-$rect.T)*0.68))
            [WindowCaptureNative]::mouse_event(0x0800,0,0,-1800,[UIntPtr]::Zero)
            [void][WindowCaptureNative]::SetCursorPos($cursor.X,$cursor.Y)
        }
        $wait={for($w=0;$w -lt $WaitMilliseconds;$w+=100){if((Stopped) -or [WindowCaptureNative]::GetForegroundWindow() -ne $handle){break};Start-Sleep -Milliseconds 100}}
        $probe={ReadCurrentText $handle}
        $focus={[WindowCaptureNative]::GetForegroundWindow() -eq $handle}
        $stop={Stopped}
        $progress={param($message) Emit 'progress' $message}
        $initialDocuments=$documents
        try{$scrollResult=Invoke-FinalScroll $probe $scroll $wait $stop $focus $progress $MaximumSteps}
        catch{$scrollResult=@{steps=0;bottom_stable=$false;reason=('快速滚动异常，底部未确认：'+$_.Exception.Message);last_text=''}}
        $reason=$scrollResult.reason
        try{$documents=ReadDocuments $handle -AllowStopped}catch{$documents=@()}
        if(-not @($documents|Where-Object {$_.text}).Count){
            $documents=$initialDocuments;$scrollResult.bottom_stable=$false
            $reason+='；最终文本不可读，已保留初始文本'
        }
        $primary=-1
        for($i=0;$i -lt $documents.Count;$i++){if($documents[$i].text){$primary=$i}}
        $marker=[bool]($documents[$primary].text -match '已经到底|没有更多了|暂无更多|已显示全部')
        if($scrollResult.bottom_stable -and ($documents[$primary].text -cne $scrollResult.last_text -or (Stopped) -or [WindowCaptureNative]::GetForegroundWindow() -ne $handle)){
            $scrollResult.bottom_stable=$false;$reason='最终读取时文本或窗口状态变化，底部稳定状态未确认'
        }
        $current=[ordered]@{captured_at=[DateTimeOffset]::Now.ToString('o');window_title=(WindowTitle $handle);window_handle=[long]$handle;step=$scrollResult.steps;primary_document_index=$primary;bottom_confirmed=($marker -and $scrollResult.bottom_stable);bottom_marker_present=$marker;bottom_stable=$scrollResult.bottom_stable;collection_mode='final_only';documents=@($documents)}
        $file=Join-Path $SaveDirectory ('raw-{0:D4}.json' -f $scrollResult.steps)
        $current|ConvertTo-Json -Depth 8|Set-Content -LiteralPath $file -Encoding UTF8
        Emit 'snapshot' @{file=$file;step=$scrollResult.steps;bottom_confirmed=$current.bottom_confirmed;characters=(@($documents|ForEach-Object {$_.length})|Measure-Object -Sum).Sum;final_only=$true}
    }elseif($AutoScroll -and -not $current.bottom_confirmed){
        if([WindowCaptureNative]::IsIconic($handle)){[void][WindowCaptureNative]::ShowWindow($handle,9)}
        [void][WindowCaptureNative]::SetForegroundWindow($handle)
        Start-Sleep -Milliseconds 350
        if([WindowCaptureNative]::GetForegroundWindow() -ne $handle){throw '无法激活目标窗口；已保存初始文本。请手动滚动后使用直接采集。'}
        Emit 'progress' '自动向下滚动中；按 Esc 或点击停止可终止。请保持目标窗口在前台。'
        $reason='达到滚动步数上限；底部状态未确认'
        for($step=1;$step -le $MaximumSteps;$step++){
            if(Stopped){$reason='用户停止，已保留完成的快照';break}
            if([WindowCaptureNative]::GetForegroundWindow() -ne $handle){$reason='目标窗口失去焦点，已停止滚动';break}
            $rect=New-Object WindowCaptureNative+RECT;[void][WindowCaptureNative]::GetWindowRect($handle,[ref]$rect)
            $cursor=New-Object WindowCaptureNative+POINT;[void][WindowCaptureNative]::GetCursorPos([ref]$cursor)
            [void][WindowCaptureNative]::SetCursorPos([int](($rect.L+$rect.R)/2),[int]($rect.T+($rect.B-$rect.T)*0.68))
            [WindowCaptureNative]::mouse_event(0x0800,0,0,-600,[UIntPtr]::Zero)
            [void][WindowCaptureNative]::SetCursorPos($cursor.X,$cursor.Y)
            for($wait=0;$wait -lt $WaitMilliseconds;$wait+=100){if(Stopped){break};Start-Sleep -Milliseconds 100}
            if(Stopped){$reason='用户停止，已保留完成的快照';break}
            $documents=ReadDocuments $handle
            if(-not @($documents|Where-Object {$_.text}).Count){$reason='页面文本暂不可读，已保留此前快照';break}
            $current=SaveSnapshot $handle $step $documents
            if($current.bottom_confirmed){$reason='检测到当前文档的底部文字提示';break}
            $fingerprint=($current.documents|ConvertTo-Json -Compress -Depth 6)
            if($fingerprint -eq $previous){$stable++}else{$stable=0}
            $previous=$fingerprint
            if($stable -ge 5){$reason='连续5次文本不变；可能滚动未生效，底部状态未确认';break}
        }
    }elseif($current.bottom_confirmed){$reason='当前文档已有底部文字提示，无需自动滚动'}
    try{SaveScreenshot $handle}catch{Emit 'progress' ('截图未保存：'+$_.Exception.Message)}
    Emit 'done' @{reason=$reason;bottom_confirmed=$current.bottom_confirmed;last_step=$current.step}
    exit 0
}catch{
    Emit 'error' $_.Exception.Message
    exit 1
}
