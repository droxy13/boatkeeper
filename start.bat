@echo off
echo.
echo ============================================
echo   BoatKeeper Online Server
echo ============================================
echo.
echo Starting server...
echo.
echo Open your browser and go to:
echo   http://localhost:5000
echo.
echo Default login:
echo   Username: admin
echo   Password: admin123
echo.
echo Press Ctrl+C to stop the server.
echo ============================================
echo.

cd /d "%~dp0"
python app.py

pause
