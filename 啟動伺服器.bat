@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: 自動在桌面建立捷徑（只建一次）
set SHORTCUT=%USERPROFILE%\Desktop\啟動SPC監控台.lnk
if not exist "%SHORTCUT%" (
    powershell -Command "$s=(New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%');$s.TargetPath='%~f0';$s.WorkingDirectory='%~dp0';$s.Description='FLH SPC Dashboard';$s.Save()"
    echo 已在桌面建立捷徑
)

python server.py
pause
