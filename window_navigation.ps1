param([ValidateSet('inspect','focus','back','click','type','key','point','top')][string]$Mode='inspect',
      [long]$WindowHandle,[string]$Text='',[string]$TextBase64='',[string]$AfterBase64='',[double]$X=0,[double]$Y=0,[int]$Key=13)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class NavigateNative {
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
 [StructLayout(LayoutKind.Sequential)] public struct KEYBOARD {public ushort vk,scan;public uint flags,time;public UIntPtr extra;}
 [StructLayout(LayoutKind.Sequential)] public struct MOUSE {public int x,y;public uint data,flags,time;public UIntPtr extra;}
 [StructLayout(LayoutKind.Explicit)] public struct UNION {[FieldOffset(0)] public KEYBOARD keyboard;[FieldOffset(0)] public MOUSE mouse;}
 [StructLayout(LayoutKind.Sequential)] public struct INPUT {public uint type;public UNION u;}
 [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int n);
 [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h,out RECT r);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x,int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint flags,uint x,uint y,int data,UIntPtr extra);
 [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
 [DllImport("user32.dll")] public static extern uint SendInput(uint count,INPUT[] inputs,int size);
 public static void Key(ushort key,bool up){INPUT i=new INPUT();i.type=1;i.u.keyboard.vk=key;i.u.keyboard.flags=up?2u:0u;if(SendInput(1,new INPUT[]{i},Marshal.SizeOf(typeof(INPUT)))!=1)throw new Exception("Keyboard input rejected");}
 public static void Type(string text){foreach(char c in text){INPUT a=new INPUT();a.type=1;a.u.keyboard.scan=c;a.u.keyboard.flags=4;INPUT b=a;b.u.keyboard.flags=6;if(SendInput(2,new INPUT[]{a,b},Marshal.SizeOf(typeof(INPUT)))!=2)throw new Exception("Text input rejected");}}
}
'@
function Get-TextPoint($Boxes, $Bounds) {
 foreach($box in $Boxes){
  $px=$box.X+$box.Width/2; $py=$box.Y+$box.Height/2
  if($box.Width -gt 0 -and $box.Height -gt 0 -and $px -gt $Bounds.L+15 -and $px -lt $Bounds.R-15 -and $py -gt $Bounds.T+35 -and $py -lt $Bounds.B-15){
   return @{X=[int]$px;Y=[int]$py}
  }
 }
 return $null
}
function Test-TextName([string]$Actual,[string]$Expected) {
 return (($Actual.Normalize() -replace '[（]','(' -replace '[）]',')' -replace '\s+',' ').Trim() -ceq ($Expected.Normalize() -replace '[（]','(' -replace '[）]',')' -replace '\s+',' ').Trim())
}
function Get-MatchingTextRectangles($Nodes,[string]$Expected,[bool]$MallResult=$false) {
 $baseName='';$suffix=''
 if($Expected -match '^(.+?)([（(][^（）()]+[）)])$'){$baseName=$Matches[1];$suffix=$Matches[2]}
 foreach($node in $Nodes){
  $name=$node.Current.Name;$box=$node.Current.BoundingRectangle
  $matched=Test-TextName $name $Expected
  if(-not $matched -and $baseName -and (Test-TextName $name $baseName)){
   foreach($part in $Nodes){
    $partBox=$part.Current.BoundingRectangle
    if((Test-TextName $part.Current.Name $suffix) -and [Math]::Abs($partBox.Top-$box.Top) -lt $box.Height*.4 -and [Math]::Abs($partBox.Left-$box.Right) -lt $box.Height){$matched=$true;break}
   }
  }
  if(-not $matched){continue}
  if($MallResult){
   $category=$false
   foreach($part in $Nodes){
    $partBox=$part.Current.BoundingRectangle
    if($part.Current.Name -in @('商场','购物中心','百货商场') -and [Math]::Abs($partBox.Left-$box.Left) -lt $box.Height -and $partBox.Top -gt $box.Bottom -and $partBox.Top-$box.Bottom -lt $box.Height*4){$category=$true;break}
   }
   if(-not $category){continue}
  }
  $box
 }
}
function Get-VisibleTextPoint([scriptblock]$ReadBoxes,[scriptblock]$Scroll,$Bounds,[int]$MaximumScrolls=0) {
 for($step=0;$step -le $MaximumScrolls;$step++){
  $point=Get-TextPoint @(& $ReadBoxes) $Bounds
  if($null -ne $point){return $point}
  if($step -lt $MaximumScrolls){& $Scroll}
 }
 return $null
}
try {
 [void][NavigateNative]::SetProcessDPIAware()
 if($TextBase64){$Text=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($TextBase64))}
 $handle=[IntPtr]$WindowHandle
 if(-not [NavigateNative]::IsWindow($handle)){throw '目标窗口已关闭'}
 if([NavigateNative]::GetAsyncKeyState(0x1B) -lt 0){throw '用户按Esc停止'}
 if($Mode -eq 'focus'){
  [void][NavigateNative]::ShowWindow($handle,9);[void][NavigateNative]::SetForegroundWindow($handle)
  Start-Sleep -Milliseconds 250
 }
 if($Mode -ne 'inspect' -and [NavigateNative]::GetForegroundWindow() -ne $handle){throw '目标窗口失去焦点，已停止自动操作'}
 $rect=New-Object NavigateNative+RECT
 [void][NavigateNative]::GetWindowRect($handle,[ref]$rect)
 function ClickAt([int]$x,[int]$y){
  if($x -le $rect.L -or $x -ge $rect.R -or $y -le $rect.T -or $y -ge $rect.B){throw '点击位置不在目标窗口内'}
  if([NavigateNative]::GetForegroundWindow() -ne $handle){throw '点击前目标窗口失去焦点'}
  [void][NavigateNative]::SetCursorPos($x,$y)
  [NavigateNative]::mouse_event(2,0,0,0,[UIntPtr]::Zero)
  [NavigateNative]::mouse_event(4,0,0,0,[UIntPtr]::Zero)
 }
 function Documents {
  $root=[Windows.Automation.AutomationElement]::FromHandle($handle)
  $condition=New-Object Windows.Automation.PropertyCondition ([Windows.Automation.AutomationElement]::ControlTypeProperty),([Windows.Automation.ControlType]::Document)
  $elements=$root.FindAll([Windows.Automation.TreeScope]::Descendants,$condition)
  $values=@()
  foreach($doc in $elements){
   try{$pattern=$doc.GetCurrentPattern([Windows.Automation.TextPattern]::Pattern);$value=$pattern.DocumentRange.GetText(-1)
    if($value){$values+=@{element=$doc;pattern=$pattern;text=$value;name=$doc.Current.Name}}
   }catch{}
  }
  return ,$values
 }
 switch($Mode){
  'inspect' {
   $docs=Documents
   $values=@($docs|ForEach-Object {@{name=$_.name;text=$_.text}})
   @{ok=$true;documents=$values;primary_document_index=($values.Count-1);rect=@($rect.L,$rect.T,$rect.R,$rect.B)}|ConvertTo-Json -Depth 7 -Compress
   exit 0
  }
  'back' {ClickAt ([int]($rect.L+($rect.R-$rect.L)*0.055)) ([int]($rect.T+($rect.R-$rect.L)*0.097))}
  'point' {ClickAt ([int]($rect.L+($rect.R-$rect.L)*$X)) ([int]($rect.T+($rect.B-$rect.T)*$Y))}
  'key' {[NavigateNative]::Key([uint16]$Key,$false);[NavigateNative]::Key([uint16]$Key,$true)}
  'type' {
   [NavigateNative]::Key(17,$false);[NavigateNative]::Key(65,$false);[NavigateNative]::Key(65,$true);[NavigateNative]::Key(17,$true)
   [NavigateNative]::Type($Text)
  }
  'top' {
   [void][NavigateNative]::SetCursorPos([int]($rect.L+($rect.R-$rect.L)*0.6),[int]($rect.T+($rect.B-$rect.T)*0.45))
   [NavigateNative]::mouse_event(0x0800,0,0,18000,[UIntPtr]::Zero)
  }
  'click' {
   $docs=Documents
   if(-not $docs.Count){throw '当前窗口无可读文档'}
   $clicked=$false
   $bounds=@{L=$rect.L;T=$rect.T;R=$rect.R;B=$rect.B}
   if($AfterBase64){
    $after=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($AfterBase64))
    $anchorCondition=New-Object Windows.Automation.PropertyCondition ([Windows.Automation.AutomationElement]::NameProperty),$after
    $anchorPoint=$null
    foreach($doc in $docs){
     $anchors=$doc.element.FindAll([Windows.Automation.TreeScope]::Descendants,$anchorCondition)
     foreach($anchor in $anchors){
      $anchorPoint=Get-TextPoint @($anchor.Current.BoundingRectangle) $bounds
      if($null -ne $anchorPoint){break}
     }
     if($null -ne $anchorPoint){break}
    }
    if($null -eq $anchorPoint){throw ('点击区域锚点当前不可见：'+$after)}
    $bounds.T=$anchorPoint.Y-35
   }
   # Mini-program TextRange endpoints can skip characters; prefer named nodes.
   $readBoxes={
    $currentDocs=Documents
    for($di=$currentDocs.Count-1;$di -ge 0;$di--){
     $named=$currentDocs[$di].element.FindAll([Windows.Automation.TreeScope]::Descendants,[Windows.Automation.Condition]::TrueCondition)
     Get-MatchingTextRectangles $named $Text ([bool]$AfterBase64)
    }
   }
   $scroll={
    if([NavigateNative]::GetForegroundWindow() -ne $handle){throw '滚动前目标窗口失去焦点'}
    if([NavigateNative]::GetAsyncKeyState(0x1B) -lt 0){throw '用户按Esc停止'}
    [void][NavigateNative]::SetCursorPos([int]($rect.L+($rect.R-$rect.L)*0.6),[int]($rect.T+($rect.B-$rect.T)*0.6))
    [NavigateNative]::mouse_event(0x0800,0,0,-480,[UIntPtr]::Zero)
    Start-Sleep -Milliseconds 350
   }
   $maximumScrolls=0
   if($AfterBase64){$maximumScrolls=2}
   elseif($Text -match '^查看全部\s*\d+\s*家门店'){$maximumScrolls=5}
   $point=Get-VisibleTextPoint $readBoxes $scroll $bounds $maximumScrolls
   if($null -ne $point){ClickAt $point.X $point.Y;$clicked=$true}
   if(-not $clicked -and -not $AfterBase64){
    foreach($doc in $docs){
     try{
      $range=$doc.pattern.DocumentRange.Clone().FindText($Text,$false,$false)
      if($range){
       $point=Get-TextPoint ($range.GetBoundingRectangles()) $bounds
       if($null -ne $point){ClickAt $point.X $point.Y;$clicked=$true;break}
      }
     }catch [System.Runtime.InteropServices.COMException]{continue}
    }
   }
   if(-not $clicked){throw ('当前可见区域未找到可点击文字：'+$Text)}
  }
 }
 @{ok=$true;action=$Mode}|ConvertTo-Json -Compress
}catch{
 @{ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress
 exit 1
}
