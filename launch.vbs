' Hermes CoAgent Server Launcher v3 - Simple version
' Just kills old pythonw and launches fresh. No verification.
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
For Each p In procs
    p.Terminate()
Next
On Error Goto 0
WScript.Sleep 2000
CreateObject("WScript.Shell").Run "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe ""C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py"" 9123", 0, False
