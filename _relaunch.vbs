CreateObject("WScript.Shell").Run "C:\Users\Admin\AppData\Local\Programs\Python\Python313\pythonw.exe "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py" 9123", 0, False
Set fso = CreateObject("Scripting.FileSystemObject")
fso.DeleteFile "C:\Users\Admin\Desktop\Hermes CoAgent\_relaunch.vbs"
