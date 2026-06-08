@echo off
echo Building DALSA Camera DLL...

:: Set paths with known locations
set SAPERA_ROOT=C:\Program Files\Teledyne DALSA\Sapera
set SAPERA_INCLUDE_BASIC=%SAPERA_ROOT%\Classes\Basic
set SAPERA_INCLUDE_GUI=%SAPERA_ROOT%\Classes\Gui
set SAPERA_INCLUDE_MAIN=%SAPERA_ROOT%\Include
set SAPERA_LIB_WIN64=%SAPERA_ROOT%\Lib\Win64
set SAPERA_LIB_WIN32=%SAPERA_ROOT%\Lib\Win32

echo Current directory: %CD%
echo.
echo Files before build:
dir *.dll 2>nul
dir *.obj 2>nul
echo.

:: Find and setup Visual Studio environment
echo Setting up Visual Studio environment...

call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" 2>nul
if errorlevel 1 (
    call "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat" 2>nul
)
if errorlevel 1 (
    call "C:\Program Files(x86)\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat" 2>nul
)
if errorlevel 1 (
    echo ERROR: Could not find Visual Studio environment
    pause
    exit /b 1
)

echo Compiler location:
where cl.exe
echo.

:: Check if source file exists
if not exist "DalsaCamera.cpp" (
    echo ERROR: DalsaCamera.cpp not found in current directory!
    echo Current directory contents:
    dir *.cpp
    pause
    exit /b 1
)

echo Source file found: DalsaCamera.cpp
echo.

:: Build for x64 with verbose output
echo Building x64 version with verbose output...
echo Command line:
echo cl.exe /LD /EHsc DalsaCamera.cpp /I"%SAPERA_INCLUDE_BASIC%" /I"%SAPERA_INCLUDE_GUI%" /I"%SAPERA_INCLUDE_MAIN%" /link /LIBPATH:"%SAPERA_LIB_WIN64%" SapClassBasic.lib /Fe:DalsaCamera_x64.dll

cl.exe /LD /EHsc DalsaCamera.cpp ^
  /I"%SAPERA_INCLUDE_BASIC%" ^
  /I"%SAPERA_INCLUDE_GUI%" ^
  /I"%SAPERA_INCLUDE_MAIN%" ^
  /link /LIBPATH:"%SAPERA_LIB_WIN64%" ^
  SapClassBasic.lib ^
  /OUT:DalsaCamera_x64.dll

echo.
echo Compilation exit code: %ERRORLEVEL%
echo.

echo Files after build attempt:
dir *.dll 2>nul
dir *.obj 2>nul
dir *.exp 2>nul
dir *.lib 2>nul
echo.

if exist "DalsaCamera_x64.dll" (
    echo SUCCESS: DalsaCamera_x64.dll created!
    echo File size:
    dir DalsaCamera_x64.dll
) else (
    echo DLL not created. Checking for intermediate files...
    if exist "DalsaCamera.obj" (
        echo Object file was created, but linking failed.
        echo Trying manual linking...
        link.exe /DLL DalsaCamera.obj /LIBPATH:"%SAPERA_LIB_WIN64%" SapClassBasic.lib /OUT:DalsaCamera_x64.dll
    ) else (
        echo Object file not created - compilation failed.
        echo.
        echo Trying simple test compilation...
        echo #include ^<iostream^> > test.cpp
        echo int main(){std::cout ^<^< "test" ^<^< std::endl; return 0;} >> test.cpp
        cl.exe test.cpp /Fe:test.exe
        if exist "test.exe" (
            echo Basic compilation works.
        ) else (
            echo Basic compilation also fails - check Visual Studio setup.
        )
    )
)

pause