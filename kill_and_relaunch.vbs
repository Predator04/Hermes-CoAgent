' Hermes CoAgent — Double-click this to FORCE RELAUNCH with desktop access
' Created for: William, Predator04

' Step 1: Kill any old pythonw processes
On Error Resume Next
Set wmi = GetObject("winmgmts:\\.\root\cimv2")
Set procs = wmi.ExecQuery("SELECT * FROM Win32_Process WHERE Name='pythonw.exe'")
For Each p In procs
    p.Terminate()
Next
On Error Goto 0

WScript.Sleep 2000

' Step 2: Launch server fresh
Dim shell
Set shell = CreateObject("WScript.Shell")
shell.Run "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe ""C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py"" 9123", 0, False

WScript.Sleep 2000

' Step 3: Verify
Dim http
Set http = CreateObject("MSXML2.XMLHTTP")
http.open "GET", "http://localhost:9123/ping", False
http.send
If http.Status = 200 Then
    MsgBox "Server running!" & vbCrLf & http.responseText, vbInformation, "Hermes CoAgent"
Else
    MsgBox "Server failed to start (HTTP " & http.Status & ")", vbExclamation, "Hermes CoAgent"
End If
