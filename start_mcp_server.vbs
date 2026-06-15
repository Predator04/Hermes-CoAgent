' Launch Hermes Windows Computer Use MCP Server (no cmd window)
' Hermes will auto-connect via mcp_servers config
' This is a manual launcher if you want to run it standalone

Set WshShell = CreateObject("WScript.Shell")
strPython = """C:\Users\Admin\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"""
strScript = """C:\Users\Admin\Desktop\Hermes CoAgent\computer_use_mcp.py"""
strCmd = strPython & " " & strScript & " --http --port 9124"

' Run hidden (0 = hidden window)
WshShell.Run strCmd, 0, False
