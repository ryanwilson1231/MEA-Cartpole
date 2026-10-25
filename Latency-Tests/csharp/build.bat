@echo off
REM Build the native C# latency test.
REM Uses the C# compiler that ships with Windows (.NET Framework 4.x) - no SDK install needed.

setlocal

set CSC=C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe
set DLLSRC=%~dp0..\..\Hardware-Pythonnet-Path\McsUsbNet.dll

if not exist "%CSC%" (
  echo ERROR: csc.exe not found at %CSC%
  echo Install the .NET Framework 4.x developer files, or use the .NET SDK instead.
  exit /b 1
)

if not exist "%DLLSRC%" (
  echo ERROR: McsUsbNet.dll not found at %DLLSRC%
  exit /b 1
)

REM Copy the DLL next to the exe and strip the mark-of-the-web.
REM Without this, .NET refuses to load it ("assembly from a network location").
copy /Y "%DLLSRC%" "%~dp0McsUsbNet.dll" >nul
powershell -NoProfile -Command "Unblock-File -Path '%~dp0McsUsbNet.dll'"

echo Compiling...
"%CSC%" /nologo /platform:x64 /optimize+ /out:"%~dp0LatencyTest.exe" ^
        /reference:"%~dp0McsUsbNet.dll" "%~dp0LatencyTest.cs"

if errorlevel 1 (
  echo.
  echo BUILD FAILED.
  echo If the errors are about method signatures, the DLL version may differ.
  echo Run the pythonnet branch's reflection dump to see the real API.
  exit /b 1
)

echo.
echo Build OK -^> LatencyTest.exe
echo   LatencyTest.exe            record-only timing
echo   LatencyTest.exe --stim     + round-trip latency  (SALINE ONLY)
endlocal
