@echo off
for %%c in (inventory cost metrics utilization waste forecast activity alerts security) do (
  echo.
  echo ===== %%c =====
  call "%~dp0collect.cmd" %%c
)