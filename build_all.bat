@echo off
setlocal
cd /d "%~dp0"

echo.
echo === Legal Doc Migration - Build ===
echo.

echo [1/5] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found on PATH.
    pause
    exit /b 1
)

echo.
echo [2/5] Installing/upgrading dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo.
echo [3/5] Running automated tests (stops the build if anything is broken)...
python -m pytest tests -v
if errorlevel 1 (
    echo ERROR: Tests failed - build stopped so a broken app is never produced.
    pause
    exit /b 1
)

echo.
if not exist "vendor\tesseract\tesseract.exe" (
    echo WARNING: OCR will NOT be bundled - run get_ocr_helpers.bat first.
    echo.
)

echo [4/5] Cleaning previous build artifacts...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo.
echo [5/5] Running PyInstaller...
python -m PyInstaller legal_migration.spec --noconfirm --clean
if errorlevel 1 (
    echo ERROR: PyInstaller build failed.
    pause
    exit /b 1
)

echo.
if exist "dist\LegalDocMigration\LegalDocMigration.exe" (
    echo SUCCESS! App ready at:
    echo   %cd%\dist\LegalDocMigration\LegalDocMigration.exe
) else (
    echo ERROR: Build finished but the .exe was not found.
)
echo.
pause
