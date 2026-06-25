$WshShell = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath('Desktop')
$shortcut = $WshShell.CreateShortcut("$desktop\HandleAI Moksh.lnk")
$shortcut.TargetPath = "C:\Users\moksh\OneDrive\Documents\.venv-1\Scripts\python.exe"
$shortcut.Arguments = "C:\Users\moksh\OneDrive\Documents\portfolio\pew\pew.py"
$shortcut.WorkingDirectory = "C:\Users\moksh\OneDrive\Documents\portfolio\pew"
$shortcut.IconLocation = "C:\Windows\System32\imageres.dll, 70"
$shortcut.Save()
Write-Output "Desktop shortcut created."
