' Hermes CoAgent Server Launcher
' Kills old server processes, then launches server fresh

' Step 1: Kill old server processes only
On Error Resume Next
Set wmi = GetObject("winmgmts:\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe' AND CommandLine LIKE '%hermes_coagent%'")
For Each p In procs
    p.Terminate()
Next
On Error Goto 0
WScript.Sleep 2000

' Step 2: Launch server
Set shell = CreateObject("WScript.Shell")
shell.Run "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe ""C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py"" 9123", 0, False
