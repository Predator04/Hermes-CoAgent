; CoAgent Windows Installer — NSIS script
; Build with: "C:\Program Files (x86)\NSIS\Bin\makensis.exe" coagent_installer.nsi

!define PRODUCT_NAME "CoAgent"
!define PRODUCT_VERSION "8.23"
!define PRODUCT_PUBLISHER "Hermes CoAgent"
!define PRODUCT_WEB_SITE "https://github.com/Predator04/Hermes-CoAgent"
!define PRODUCT_DIR "$LOCALAPPDATA\CoAgent"
!define PRODUCT_STARTMENU "$SMPROGRAMS\CoAgent"
!define PRODUCT_UNINST_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCT_NAME}"

SetCompressor lzma
RequestExecutionLevel admin
XPStyle on

Name "${PRODUCT_NAME} ${PRODUCT_VERSION}"
OutFile "CoAgent_Setup_${PRODUCT_VERSION}.exe"
InstallDir "${PRODUCT_DIR}"
ShowInstDetails show
ShowUnInstDetails show

; ── Modern UI ──
!include "MUI2.nsh"
!include "FileFunc.nsh"
; nsProcess not available — use taskkill in sections instead

; Interface Settings
!define MUI_ABORTWARNING
!define MUI_ICON "coagent_icon.ico"
!define MUI_UNICON "coagent_icon.ico"
!define MUI_HEADERIMAGE

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY

; Components page
!define MUI_PAGE_CUSTOMFUNCTION_PRE components_pre
!insertmacro MUI_PAGE_COMPONENTS

!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ── Components ──
Section "CoAgent Server (required)" SEC_CORE
    SectionIn RO
    SetOutPath "$INSTDIR"

    ; Kill running CoAgent
    nsExec::ExecToStack 'taskkill /f /im CoAgent.exe 2>nul'
    nsExec::ExecToStack 'taskkill /f /im pythonw.exe 2>nul'

    ; Main server files
    File "hermes_coagent.py"
    File "shared.py"
    File "auth.py"
    File "screenshot_relay.py"
    File "uia_engine.py"
    File "tray_icon.py"
    File "launch_all.ps1"
    File "LICENSE"
    File "README.md"
    File "requirements.txt"

    ; Route modules
    File "routes_mouse.py"
    File "routes_ocr.py"
    File "routes_uia.py"
    File "routes_file.py"
    File "routes_media.py"
    File "routes_system.py"
    File "routes_v63.py"
    File "routes_stream.py"
    File "routes_process.py"
    File "routes_voice.py"
    File "routes_cua.py"
    File "routes_buddy.py"
    File "routes_bypass.py"
    File "routes_toast.py"
    File "routes_config.py"
    File "routes_browser.py"
    File "browser_automation.py"
    File "routes_google.py"
    File "routes_logs.py"
    File "routes_recorder.py"
    File "routes_git.py"
    File "routes_dashboard.py"
    File "routes_obsidian.py"
    File "routes_wol.py"
    File "routes_phone.py"
    File "routes_webrtc.py"
    File "routes_plugins.py"
    File "routes_palmreject.py"
    File "routes_agent.py"
    File "routes_telegram.py"
    File "routes_memory.py"
    File "routes_reminders.py"
    File "routes_mcp.py"
    File "routes_hud.py"
    File "routes_recorder_gif.py"
    File "routes_undo.py"
    File "routes_diff.py"
    File "routes_finder.py"
    File "routes_metrics.py"
    File "routes_docs.py"
    File "routes_updates.py"
    File "routes_webhooks.py"
    File "routes_copilot.py"
    File "routes_copilot_enhanced.py"
    File "routes_recipes.py"
    File "routes_healer.py"
    File "routes_browser_final.py"
    File "routes_mobile.py"
    File "routes_help.py"
    File "routes_deps.py"
    File "routes_crack.py"

    ; Auto feature routes
    File "routes_auto_winchronicle.py"
    File "routes_auto_gpt4all.py"
    File "routes_auto_open_interpreter.py"
    File "routes_auto_windows_ai_toolkit.py"
    File "routes_auto_powertoys.py"
    File "routes_auto_obs_studio.py"
    File "routes_auto_ghidra.py"
    File "routes_auto_apktool.py"
    File "routes_auto_devika.py"
    File "routes_auto_plandex.py"
    File "routes_auto_tmuxp.py"
    File "routes_auto_pywinauto.py"
    File "routes_auto_rapidocr.py"
    File "routes_auto_sharpdxscreencapture.py"
    File "routes_auto_cognee.py"

    ; Tools
    File "nircmd.exe"
    File "install_coagent.py"

    ; Write uninstaller
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Start menu shortcut
    CreateDirectory "${PRODUCT_STARTMENU}"
    SetOutPath "$INSTDIR"
    CreateShortCut "${PRODUCT_STARTMENU}\CoAgent.lnk" "$INSTDIR\CoAgent.exe" "" "$INSTDIR\CoAgent.exe" 0
    CreateShortCut "${PRODUCT_STARTMENU}\Uninstall CoAgent.lnk" "$INSTDIR\uninstall.exe" "" "$INSTDIR\uninstall.exe" 0

    ; Desktop shortcut
    CreateShortCut "$DESKTOP\CoAgent.lnk" "$INSTDIR\CoAgent.exe" "" "$INSTDIR\CoAgent.exe" 0

    ; Registry for Add/Remove Programs
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayName" "${PRODUCT_NAME}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayVersion" "${PRODUCT_VERSION}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "Publisher" "${PRODUCT_PUBLISHER}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "URLInfoAbout" "${PRODUCT_WEB_SITE}"
    WriteRegStr HKLM "${PRODUCT_UNINST_KEY}" "DisplayIcon" "$INSTDIR\CoAgent.exe"
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoModify" 1
    WriteRegDWORD HKLM "${PRODUCT_UNINST_KEY}" "NoRepair" 1

    ; Generate auth token on first run
    ; Token will be generated when server starts with --secure
SectionEnd

Section "CoAgent.exe (standalone, ~71MB)" SEC_EXE
    SectionIn 1
    File "dist\CoAgent.exe"
SectionEnd

Section "Auto-start on login" SEC_AUTOSTART
    ; Create scheduled task to launch CoAgent at user logon
    nsExec::ExecToStack 'cmd /c schtasks /create /tn "CoAgent" /tr "$INSTDIR\CoAgent.exe" /sc onlogon /ru "%USERNAME%" /it /f /delay 0000:30'
    Pop $0
SectionEnd

Section "Desktop shortcut" SEC_DESKSHORTCUT
    CreateShortCut "$DESKTOP\CoAgent.lnk" "$INSTDIR\CoAgent.exe" "" "$INSTDIR\CoAgent.exe" 0
SectionEnd

; ── Descriptions ──
LangString DESC_SEC_CORE ${LANG_ENGLISH} "Core CoAgent server files and all route modules (required)"
LangString DESC_SEC_EXE ${LANG_ENGLISH} "Standalone CoAgent.exe compiled with PyInstaller (~71MB). No Python required."
LangString DESC_SEC_AUTOSTART ${LANG_ENGLISH} "Register CoAgent to start automatically when you log in to Windows"
LangString DESC_SEC_DESKSHORTCUT ${LANG_ENGLISH} "Create a shortcut on your Desktop"

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_CORE} $(DESC_SEC_CORE)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_EXE} $(DESC_SEC_EXE)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_AUTOSTART} $(DESC_SEC_AUTOSTART)
    !insertmacro MUI_DESCRIPTION_TEXT ${SEC_DESKSHORTCUT} $(DESC_SEC_DESKSHORTCUT)
!insertmacro MUI_FUNCTION_DESCRIPTION_END

Function components_pre
    ; Pre-select EXE if available
    IfFileExists "$EXEDIR\dist\CoAgent.exe" +2
        SectionSetFlags ${SEC_EXE} ${SF_PSELECTED}
FunctionEnd

; ── Uninstaller ──
Section "Uninstall"
    ; Stop CoAgent
    nsExec::ExecToStack 'taskkill /f /im CoAgent.exe 2>nul'
    nsExec::ExecToStack 'taskkill /f /im pythonw.exe 2>nul'

    ; Remove scheduled task
    nsExec::ExecToStack 'schtasks /delete /tn "CoAgent" /f'
    nsExec::ExecToStack 'schtasks /delete /tn "CoAgent-Screenshot-Relay" /f'

    ; Remove shortcuts
    RMDir /r "${PRODUCT_STARTMENU}"
    Delete "$DESKTOP\CoAgent.lnk"

    ; Remove registry keys
    DeleteRegKey HKLM "${PRODUCT_UNINST_KEY}"

    ; Preserve user data, remove program files
    IfFileExists "$INSTDIR\.token" 0 +2
        Rename "$INSTDIR\.token" "$TEMP\coagent_token.bak"
    IfFileExists "$INSTDIR\telegram_config.json" 0 +2
        Rename "$INSTDIR\telegram_config.json" "$TEMP\coagent_tg_config.bak"
    IfFileExists "$INSTDIR\config.json" 0 +2
        Rename "$INSTDIR\config.json" "$TEMP\coagent_config.bak"
    IfFileExists "$INSTDIR\recordings" 0 +2
        Rename "$INSTDIR\recordings" "$TEMP\coagent_recordings"

    RMDir /r "$INSTDIR"

    ; Restore user data prompt
    CreateDirectory "$INSTDIR"
    IfFileExists "$TEMP\coagent_token.bak" 0 +2
        Rename "$TEMP\coagent_token.bak" "$INSTDIR\.token"
    IfFileExists "$TEMP\coagent_tg_config.bak" 0 +2
        Rename "$TEMP\coagent_tg_config.bak" "$INSTDIR\telegram_config.json"
    IfFileExists "$TEMP\coagent_config.bak" 0 +2
        Rename "$TEMP\coagent_config.bak" "$INSTDIR\config.json"
    IfFileExists "$TEMP\coagent_recordings" 0 +2
        Rename "$TEMP\coagent_recordings" "$INSTDIR\recordings"
SectionEnd
