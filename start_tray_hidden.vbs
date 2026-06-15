' Hermes CoAgent Tray Launcher
' Kills all old pythonw processes, then launches tray fresh

' Step 1: Kill any existing pythonw processes
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
For Each p In procs
    p.Terminate()
Next
On Error Goto 0
WScript.Sleep 2000

' Step 2: Launch tray from the batch file
Set shell = CreateObject("WScript.Shell")
shell.Run """" & "C:\Users\Admin\Desktop\Hermes CoAgent\start_tray.bat" & """", 0, False
