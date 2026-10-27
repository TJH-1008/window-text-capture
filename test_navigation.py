import base64
import json
import os
import subprocess
import unittest
from pathlib import Path

from navigation import SHELL


@unittest.skipUnless(os.name == 'nt', 'Windows UI Automation geometry')
class NavigationGeometryTests(unittest.TestCase):
    def test_fragmented_store_title_requires_adjacent_suffix_and_mall_category(self):
        script = Path(__file__).with_name('window_navigation.ps1')
        command = r'''
Add-Type -AssemblyName WindowsBase
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
foreach($name in @('Test-TextName','Get-MatchingTextRectangles')){
 $fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
 if(-not $fn){throw ('Missing helper: '+$name)}
 Invoke-Expression $fn.Extent.Text
}
function Node($name,$x,$y,$w,$h){[pscustomobject]@{Current=[pscustomobject]@{Name=$name;BoundingRectangle=[Windows.Rect]::new($x,$y,$w,$h)}}}
$nodes=@((Node '茂业天地' 200 500 102 29),(Node '茂业天地' 200 670 102 29),(Node '(盐市口店)' 302 671 119 29),(Node '商场' 200 756 42 28))
$matches=@(Get-MatchingTextRectangles $nodes '茂业天地(盐市口店)' $true)
if($matches.Count -ne 1 -or $matches[0].Y -ne 670){throw 'Split title was not resolved to the mall result'}
$bad=@((Node '茂业天地' 200 670 102 29),(Node '(盐市口店)' 302 720 119 29),(Node '商场' 200 756 42 28))
if(@(Get-MatchingTextRectangles $bad '茂业天地(盐市口店)' $true).Count){throw 'Suffix from another row was accepted'}
$noCategory=@((Node '茂业天地' 200 670 102 29),(Node '(盐市口店)' 302 671 119 29))
if(@(Get-MatchingTextRectangles $noCategory '茂业天地(盐市口店)' $true).Count){throw 'Non-mall text was accepted as a result'}
'''.replace('SCRIPT_PATH', "'" + str(script).replace("'", "''") + "'")
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        result = subprocess.run([str(SHELL), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_text_click_scrolls_until_visible_and_handles_display_whitespace(self):
        script = Path(__file__).with_name('window_navigation.ps1')
        command = r'''
Add-Type -AssemblyName WindowsBase
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
foreach($name in @('Get-TextPoint','Get-VisibleTextPoint','Test-TextName')){
 $fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name},$true)
 if(-not $fn){throw ('Missing function: '+$name)}
 Invoke-Expression $fn.Extent.Text
}
if(-not (Test-TextName "View all 82 stores  " 'View all 82 stores')){throw 'Trailing whitespace rejected'}
if(Test-TextName 'View all 820 stores' 'View all 82 stores'){throw 'Different count accepted'}
$state=@{steps=0}
$boxes={if($state.steps -lt 2){[Windows.Rect]::new(130,900,200,30)}else{[Windows.Rect]::new(130,300,200,30)}}
$scroll={$state.steps++}
$bounds=@{L=100;T=100;R=600;B=800}
$p=Get-VisibleTextPoint $boxes $scroll $bounds 4
if($state.steps -ne 2 -or $p.Y -ne 315){throw 'Did not scroll to the visible target'}
$state.steps=0
$never={[Windows.Rect]::new(130,900,200,30)}
$p=Get-VisibleTextPoint $never $scroll $bounds 3
if($null -ne $p -or $state.steps -ne 3){throw 'Scroll bound not respected'}
'''
        command = command.replace('SCRIPT_PATH', "'" + str(script).replace("'", "''") + "'")
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        result = subprocess.run([str(SHELL), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_all_native_automation_type_references_resolve(self):
        script = Path(__file__).with_name('window_navigation.ps1')
        path_literal = "'" + str(script).replace("'", "''") + "'"
        command = '''
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
$nodes=$ast.FindAll({param($node) $node -is [Management.Automation.Language.TypeExpressionAst] -and $node.TypeName.FullName -like 'Windows.Automation.*'},$true)
$missing=@($nodes | Where-Object { $null -eq $_.TypeName.GetReflectionType() } | ForEach-Object { $_.TypeName.FullName })
if($missing.Count){throw ('Unresolved automation types: '+($missing -join ', '))}
'''.replace('SCRIPT_PATH', path_literal)
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        result = subprocess.run([str(SHELL), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_native_rectangles_skip_offscreen_and_use_visible_line_center(self):
        script = Path(__file__).with_name('window_navigation.ps1')
        command = r'''
Add-Type -AssemblyName WindowsBase
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile(SCRIPT_PATH,[ref]$tokens,[ref]$errors)
$fn=$ast.Find({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Get-TextPoint'},$true)
if(-not $fn){throw 'Get-TextPoint is missing'}
Invoke-Expression $fn.Extent.Text
$bounds=@{L=100;T=100;R=600;B=800}
$boxes=@([Windows.Rect]::new(10,10,40,20),[Windows.Rect]::new(130,160,200,30),[Windows.Rect]::new(130,200,180,30))
$point=Get-TextPoint $boxes $bounds
if($point.X -ne 230 -or $point.Y -ne 175){throw 'Incorrect visible rectangle center'}
$empty=Get-TextPoint @([Windows.Rect]::new(10,10,20,20)) $bounds
if($null -ne $empty){throw 'Offscreen text must not produce a click'}
@{x=$point.X;y=$point.Y;offscreen_rejected=$true}|ConvertTo-Json -Compress
'''
        command = command.replace('SCRIPT_PATH', "'" + str(script).replace("'", "''") + "'")
        encoded = base64.b64encode(command.encode('utf-16le')).decode('ascii')
        result = subprocess.run([str(SHELL), '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        data = json.loads(result.stdout.decode('utf-8-sig').strip())
        self.assertEqual((data['x'], data['y']), (230, 175))
        self.assertTrue(data['offscreen_rejected'])


if __name__ == '__main__':
    unittest.main()
