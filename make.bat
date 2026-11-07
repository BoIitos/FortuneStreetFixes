@echo off
rd /s /q output
md output\maps
tar -a -c -f "output\FortuneStreetFixes.zip" -C mod *.*
if errorlevel 1 goto ERROR
tar -a -c -f "output\maps\Borg.zip" -C samples\Borg *.*
if errorlevel 1 goto ERROR
tar -a -c -f "output\maps\FeelFree.zip" -C samples\FeelFree *.*
if errorlevel 1 goto ERROR
tar -a -c -f "output\maps\QuadTowers.zip" -C samples\QuadTowers *.*
if errorlevel 1 goto ERROR
tar -a -c -f "output\Samples.zip" -C mod *.py modlist.txt -C ..\output\maps *.zip -C ..\..\samples backgrounds.yml manifest.json mapList.yaml placeholder.zip
if errorlevel 1 goto ERROR
goto :EOF
:ERROR
echo Failed to create archives!
pause