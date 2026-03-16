Unicode true
RequestExecutionLevel user

!define APP_NAME "SDApp"
!define APP_VERSION "0.1.0"
!define APP_EXE "SDApp.exe"
!define APP_PROG_ID "SDApp.Project"

OutFile "SDApp-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\\SDApp"

Section "Install"
  SetOutPath "$INSTDIR"
  ; Build pipeline should copy packaged files here before installer compilation.
  ; File /r "dist\\windows\\*.*"

  WriteRegStr HKCU "Software\\Classes\\.sdproj" "" "${APP_PROG_ID}"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}" "" "SDApp Project"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}\\DefaultIcon" "" "$INSTDIR\\sdproj_doc_icon.ico"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}\\shell\\open\\command" "" '"$INSTDIR\\${APP_EXE}" "%1"'
  System::Call 'shell32::SHChangeNotify(i 0x8000000, i 0, p 0, p 0)'
SectionEnd

Section "Uninstall"
  DeleteRegKey HKCU "Software\\Classes\\${APP_PROG_ID}"
  DeleteRegValue HKCU "Software\\Classes\\.sdproj" ""
SectionEnd
