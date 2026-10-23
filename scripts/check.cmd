@echo off
if not defined FUNC_HOST call "%~dp0_env.cmd"
echo === health (expect 200) ===
curl -s -o nul -w "%%{http_code}\n" "https://%FUNC_HOST%/api/health"
echo === direct call to the Function host (expect 401) ===
curl -s -o nul -w "%%{http_code}\n" "https://%FUNC_HOST%/api/overview"
echo === collector with key (expect 200) ===
curl -s -o nul -w "%%{http_code}\n" -X POST "https://%FUNC_HOST%/api/collect/alerts" -H "x-functions-key: %FUNC_KEY%"