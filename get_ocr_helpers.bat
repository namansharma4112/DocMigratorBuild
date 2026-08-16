@echo off
setlocal
set ROOT=%~dp0
set VENDOR=%ROOT%vendor

echo.
echo === Legal Doc Migration - OCR helper downloader ===
echo.

if not exist "%VENDOR%" mkdir "%VENDOR%"

if exist "%VENDOR%\tesseract\tesseract.exe" (
    echo [1/2] Tesseract already present - skipping download.
) else (
    echo [1/2] Downloading Tesseract-OCR installer...
    set TESS_URL=https://github.com/UB-Mannheim/tesseract/releases/download/v5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe
    set TESS_INSTALLER=%TEMP%\tesseract-installer.exe
    powershell -Command "Invoke-WebRequest -Uri '%TESS_URL%' -OutFile '%TESS_INSTALLER%'"
    if not exist "%TESS_INSTALLER%" (
        echo   FAILED to download. Get it manually from
        echo   https://github.com/UB-Mannheim/tesseract/wiki
        goto poppler
    )
    "%TESS_INSTALLER%" /S /D=%VENDOR%\tesseract
    timeout /t 5 /nobreak >nul
)

:poppler
if exist "%VENDOR%\poppler\Library\bin\pdftoppm.exe" (
    echo [2/2] Poppler already present - skipping download.
) else (
    echo [2/2] Downloading Poppler for Windows...
    set POPPLER_URL=https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip
    set POPPLER_ZIP=%TEMP%\poppler.zip
    powershell -Command "Invoke-WebRequest -Uri '%POPPLER_URL%' -OutFile '%POPPLER_ZIP%'"
    if not exist "%POPPLER_ZIP%" (
        echo   FAILED to download. Get it manually from
        echo   https://github.com/oschwartz10612/poppler-windows/releases
        goto done
    )
    powershell -Command "Expand-Archive -Path '%POPPLER_ZIP%' -DestinationPath '%TEMP%\poppler_extract' -Force"
    for /d %%D in ("%TEMP%\poppler_extract\*") do (
        xcopy /E /I /Y "%%D" "%VENDOR%\poppler" >nul
    )
)

:done
echo.
echo Done. Next step: run build_all.bat
echo.
pause
