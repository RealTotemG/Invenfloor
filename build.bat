@echo off
REM ===========================================================================
REM  build.bat  --  make a release build of Invenfloor on Windows
REM
REM  Double-click it, or run it from a terminal in this folder. It redraws the
REM  icon, builds through Invenfloor.spec, and zips the result into
REM  release\Invenfloor-windows.zip, which is the file to hand to somebody.
REM
REM  First time only:   pip install -r requirements.txt
REM ===========================================================================

setlocal
cd /d "%~dp0"

echo.
echo  [1/4] checking the tools are here
where python >nul 2>nul || (
    echo.
    echo  Python is not on your PATH. Install it, or open this from a terminal
    echo  where "python" works.
    goto :failed
)
python -c "import PyInstaller" 2>nul || (
    echo  PyInstaller is missing. Installing it now.
    python -m pip install pyinstaller || goto :failed
)
python -c "import PIL" 2>nul || (
    echo  Pillow is missing, and the icon needs it. Installing it now.
    python -m pip install pillow || goto :failed
)

echo.
echo  [2/4] drawing the icon
python make_icon.py || goto :failed

echo.
echo  [3/4] building
REM  --noconfirm so a rebuild does not stop to ask about overwriting dist.
REM  --clean so a stale cached analysis cannot make this build differ from a
REM  fresh checkout's build, which is the whole point of having a spec file.
python -m PyInstaller Invenfloor.spec --noconfirm --clean || goto :failed

echo.
echo  [4/4] zipping
if not exist release mkdir release
if exist "release\Invenfloor-windows.zip" del "release\Invenfloor-windows.zip"
powershell -NoProfile -Command ^
    "Compress-Archive -Path 'dist\Invenfloor\*' -DestinationPath 'release\Invenfloor-windows.zip'" || goto :failed

echo.
echo  ==========================================================
echo   Done.
echo.
echo   Run it:    dist\Invenfloor\Invenfloor.exe
echo   Send it:   release\Invenfloor-windows.zip
echo.
echo   Your saves are NOT in either of those. They live in
echo   %%APPDATA%%\InventoryApp\data, so rebuilding or deleting
echo   the app folder cannot touch them.
echo  ==========================================================
echo.
pause
exit /b 0

:failed
echo.
echo  Build failed. The last message above says why.
echo.
pause
exit /b 1
