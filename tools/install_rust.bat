@echo off
rem ============================================================
rem  Rust installer: E:\Develop\rust  (runs elevated)
rem  Writes a full log so failures are diagnosable.
rem  ASCII only on purpose: avoids cmd codepage mangling of CJK.
rem ============================================================
setlocal
set "LOG=E:\Docs\Code\Java\book\tools\rust_install.log"
set "RUSTUP_HOME=E:\Develop\rust\rustup"
set "CARGO_HOME=E:\Develop\rust\cargo"

echo ==== rust install start ==== > "%LOG%"
echo whoami: >> "%LOG%" 2>&1
whoami >> "%LOG%" 2>&1
echo RUSTUP_HOME=%RUSTUP_HOME% >> "%LOG%"
echo CARGO_HOME=%CARGO_HOME% >> "%LOG%"

echo. >> "%LOG%"
echo [1] grant Modify on E:\Develop to Authenticated Users >> "%LOG%"
icacls "E:\Develop" /grant "*S-1-5-11:(OI)(CI)M" >> "%LOG%" 2>&1
echo icacls exit=%ERRORLEVEL% >> "%LOG%"

echo. >> "%LOG%"
echo [2] create directories >> "%LOG%"
mkdir "E:\Develop\rust" 2>> "%LOG%"
mkdir "E:\Develop\rust\rustup" 2>> "%LOG%"
mkdir "E:\Develop\rust\cargo" 2>> "%LOG%"
if exist "E:\Develop\rust\cargo" (echo   cargo dir OK >> "%LOG%") else (echo   cargo dir MISSING >> "%LOG%")

echo. >> "%LOG%"
echo [3] rustup-init (this may take several minutes) >> "%LOG%"
"E:\Docs\Code\Java\book\tools\rustup-init.exe" -y --no-modify-path --default-host x86_64-pc-windows-msvc --profile default >> "%LOG%" 2>&1
echo rustup-init exit=%ERRORLEVEL% >> "%LOG%"

echo. >> "%LOG%"
echo [4] verify >> "%LOG%"
if exist "E:\Develop\rust\cargo\bin\rustc.exe" (
  "E:\Develop\rust\cargo\bin\rustc.exe" --version >> "%LOG%" 2>&1
  "E:\Develop\rust\cargo\bin\cargo.exe" --version >> "%LOG%" 2>&1
  echo RESULT=OK >> "%LOG%"
) else (
  echo RESULT=FAIL >> "%LOG%"
)
echo ==== done ==== >> "%LOG%"
exit /b 0
