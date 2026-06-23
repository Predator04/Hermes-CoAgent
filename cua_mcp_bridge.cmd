@echo off
setlocal

set "CUA_EXE=%USERPROFILE%\AppData\Local\Programs\Cua\cua-driver\bin\cua-driver.exe"

if not exist "%CUA_EXE%" (
  echo cua_mcp_bridge: cua-driver.exe not found at "%CUA_EXE%" 1>&2
  exit /b 127
)

"%CUA_EXE%" mcp --no-overlay
exit /b %ERRORLEVEL%
