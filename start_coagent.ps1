$python = "C:\Program Files\Python312\pythonw.exe"
$script = "C:\Users\Admin\Desktop\Hermes CoAgent\hermes_coagent.py"
$workdir = "C:\Users\Admin\Desktop\Hermes CoAgent"

Set-Location $workdir
Start-Process -FilePath $python -ArgumentList "`"$script`" --secure --allow-external" -WorkingDirectory $workdir
