# Generic UI Automation capture. Only walk descendants of the selected window.
function ReadGenericWindow([IntPtr]$handle) {
    if(-not ('GenericNativeText' -as [type])){Add-Type -Path (Join-Path $PSScriptRoot 'generic_native.cs')}
    if(-not [WindowCaptureNative]::IsWindow($handle)){throw 'Selected window was closed.'}
    $root=[Windows.Automation.AutomationElement]::FromHandle($handle)
    $walker=[Windows.Automation.TreeWalker]::RawViewWalker
    $stack=New-Object System.Collections.Stack
    $stack.Push($root)
    $nodes=New-Object System.Collections.Generic.List[object]
    $clock=[Diagnostics.Stopwatch]::StartNew()
    $visited=0;$errors=0;$passwords=0;$hidden=0;$truncated=$false;$lastError='';$documents=0;$unreadableDocuments=0
    $nameTypes=@('Text','Edit','ListItem','DataItem','Hyperlink','Button','CheckBox',
                 'RadioButton','MenuItem','HeaderItem','TabItem','TreeItem','ComboBox')
    while($stack.Count){
        if((Stopped) -or $visited -ge 5000 -or $clock.Elapsed.TotalSeconds -ge 15){$truncated=$true;break}
        $node=$stack.Pop();$visited++
        try{
            $current=$node.Current
            $nativeHandle=[IntPtr]$current.NativeWindowHandle
            $class=[GenericNativeText]::ClassName($nativeHandle)
            if($current.IsPassword -or [GenericNativeText]::IsPassword($nativeHandle,$class)){$passwords++;continue}
            if($current.IsOffscreen -and $visited -gt 1){$hidden++;continue}
            $type=$current.ControlType.ProgrammaticName.Replace('ControlType.','')
            $text='';$source='';$covered=$false
            if($type -eq 'Document'){$documents++}
            if($visited -gt 1){
                $pattern=$null
                if($node.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern,[ref]$pattern)){
                    $text=$pattern.DocumentRange.GetText(262144)
                    if($text){$source='TextPattern';$covered=$true}
                    if($text.Length -ge 262144){$truncated=$true}
                }
                if(-not $text){
                    $pattern=$null
                    if($node.TryGetCurrentPattern([Windows.Automation.ValuePattern]::Pattern,[ref]$pattern)){
                        $text=$pattern.Current.Value
                        if($text){$source='ValuePattern';$covered=$type -in @('Edit','ComboBox')}
                    }
                }
                if(-not $text){
                    $native=[GenericNativeText]::Read($nativeHandle,$class)
                    if($native.Limited){$truncated=$true}
                    if($native.Text){$text=$native.Text;$source='NativeControl';$covered=$true}
                }
                if(-not $text -and $type -eq 'Pane' -and $class -match 'STATIC'){$text=$current.Name;$source='Name'}
                if(-not $text -and $type -in $nameTypes){$text=$current.Name;$source='Name'}
                if($type -eq 'Document' -and -not $text){$unreadableDocuments++}
                if(-not $text -and $type -in @('Pane','Group','Custom')){$text=$current.Name;$source='Name'}
                if(-not [string]::IsNullOrWhiteSpace($text)){
                    if($text.Length -gt 262144){$text=$text.Substring(0,262144);$truncated=$true}
                    $nodes.Add([pscustomobject]@{index=$visited;control_type=$type;name=$current.Name;
                        automation_id=$current.AutomationId;source=$source;text=$text})
                }
            }
            # A successful text pattern already covers its descendant text.
            if(-not $covered){
                $child=$walker.GetLastChild($node)
                while($child){
                    if($stack.Count -ge 5000 -or $clock.Elapsed.TotalSeconds -ge 15){$truncated=$true;break}
                    $stack.Push($child)
                    $child=$walker.GetPreviousSibling($child)
                }
            }
        }catch{$errors++;$lastError=$_.Exception.Message}
    }
    $text=(@($nodes | ForEach-Object {$_.text}) -join "`n")
    return [pscustomobject]@{
        documents=@([pscustomobject]@{name='Accessible window text';text=$text;length=$text.Length;offscreen=$false})
        nodes=@($nodes.ToArray())
        coverage=@{visited_nodes=$visited;read_errors=$errors;password_controls_skipped=$passwords;
                   offscreen_controls_skipped=$hidden;truncated=$truncated;scope='loaded_accessible_controls';last_error=$lastError;
                   document_controls=$documents;unreadable_documents=$unreadableDocuments}
    }
}

function SaveGenericSnapshot([IntPtr]$handle,[int]$step) {
    $data=ReadGenericWindow $handle
    if(-not $data.documents[0].text){throw ('No accessible text was returned. Diagnostic: '+($data.coverage|ConvertTo-Json -Compress))}
    $payload=[ordered]@{captured_at=[DateTimeOffset]::Now.ToString('o');window_title=(WindowTitle $handle);
        window_handle=[long]$handle;step=$step;primary_document_index=0;bottom_confirmed=$false;
        capture_profile='general';scroll_direction=$ScrollDirection;collection_mode='stepwise';
        documents=@($data.documents);nodes=@($data.nodes);coverage=$data.coverage}
    $file=Join-Path $SaveDirectory ('raw-{0:D4}.json' -f $step)
    $payload|ConvertTo-Json -Depth 10|Set-Content -LiteralPath $file -Encoding UTF8
    Emit 'snapshot' @{file=$file;step=$step;bottom_confirmed=$false;characters=$data.documents[0].text.Length}
    return $payload
}

function Invoke-GenericScroll($Probe,$Scroll,$Wait,$Stop,$Focus,$Progress,[int]$MaximumSteps) {
    $stable=0;$steps=0;$reason='Scroll step limit reached; completeness is unconfirmed.'
    $previous=[string](& $Probe)
    while($steps -lt $MaximumSteps){
        if(& $Stop){$reason='Stopped by user; captured snapshots are preserved.';break}
        if(-not (& $Focus)){$reason='Window lost focus; scrolling stopped.';break}
        & $Scroll
        $steps++
        & $Wait
        if(& $Stop){$reason='Stopped by user; captured snapshots are preserved.';break}
        if(-not (& $Focus)){$reason='Window lost focus; scrolling stopped.';break}
        try{$current=[string](& $Probe)}catch{$reason='Text became unreadable; previous snapshots are preserved.';break}
        if(-not $current){$reason='No readable text; previous snapshots are preserved.';break}
        if($current -ceq $previous){$stable++}else{$stable=0}
        $previous=$current
        & $Progress ('Saved scroll snapshot '+$steps)
        if($stable -ge 5){$reason='Text unchanged for 5 steps; completeness is unconfirmed.';break}
    }
    return @{steps=$steps;reason=$reason}
}

function Invoke-GenericCapture([IntPtr]$handle) {
    EnableAccessibility $handle
    $state=@{step=0;current=$null}
    $probe={
        $state.current=SaveGenericSnapshot $handle $state.step
        $state.step++
        return $state.current.documents[0].text
    }
    $reason='Captured accessible text once; completeness is unconfirmed.'
    if($AutoScroll){
        if([WindowCaptureNative]::IsIconic($handle)){[void][WindowCaptureNative]::ShowWindow($handle,9)}
        [void][WindowCaptureNative]::SetForegroundWindow($handle)
        Start-Sleep -Milliseconds 350
        if([WindowCaptureNative]::GetForegroundWindow() -ne $handle){
            [void](& $probe)
            throw 'Cannot focus selected window. Initial snapshot saved; use manual scrolling.'
        }
        $scroll={
            if((Stopped) -or [WindowCaptureNative]::GetForegroundWindow() -ne $handle){return}
            $rect=New-Object WindowCaptureNative+RECT
            [void][WindowCaptureNative]::GetWindowRect($handle,[ref]$rect)
            $cursor=New-Object WindowCaptureNative+POINT
            [void][WindowCaptureNative]::GetCursorPos([ref]$cursor)
            try{
                [void][WindowCaptureNative]::SetCursorPos([int](($rect.L+$rect.R)/2),[int]($rect.T+($rect.B-$rect.T)*0.68))
                $delta=-600;if($ScrollDirection -eq 'up'){$delta=600}
                [WindowCaptureNative]::mouse_event(0x0800,0,0,$delta,[UIntPtr]::Zero)
            }finally{[void][WindowCaptureNative]::SetCursorPos($cursor.X,$cursor.Y)}
        }
        $wait={for($w=0;$w -lt $WaitMilliseconds;$w+=100){
            if((Stopped) -or [WindowCaptureNative]::GetForegroundWindow() -ne $handle){break}
            Start-Sleep -Milliseconds 100
        }}
        $result=Invoke-GenericScroll $probe $scroll $wait {Stopped} {
            [WindowCaptureNative]::GetForegroundWindow() -eq $handle
        } {param($message) Emit 'progress' $message} $MaximumSteps
        $reason=$result.reason
    }else{[void](& $probe)}
    try{SaveScreenshot $handle}catch{Emit 'progress' ('Screenshot unavailable: '+$_.Exception.Message)}
    Emit 'done' @{reason=$reason;bottom_confirmed=$false;last_step=($state.step-1);capture_profile='general'}
}
