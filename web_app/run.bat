@echo off
title Ковровый учёт
echo ========================================
echo    Ковровый учёт - Запуск
echo ========================================
echo.
echo Запуск программы...
start python app.py
timeout /t 3 /nobreak >nul
start http://localhost:5000
echo.
echo Программа запущена!
echo Закройте окно консоли для выхода.
pause
