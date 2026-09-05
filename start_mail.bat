@echo off
cd /d "%~dp0"
echo 启动 Olivia 离线信箱服务 (http://127.0.0.1:8787) ...
"C:\Users\locea\.workbuddy\binaries\node\versions\22.22.2-2\node.exe" mail_server.js
pause
