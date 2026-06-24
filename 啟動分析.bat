@echo off
chcp 65001 >nul
echo 正在啟動 CMM 分析儀表板...
python "%~dp0server.py"
pause
