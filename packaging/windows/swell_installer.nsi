Unicode true
RequestExecutionLevel user

!define APP_NAME "Swell"
!define APP_VERSION "0.3.1"
!define APP_EXE "Swell.exe"
!define APP_PROG_ID "Swell.Project"

OutFile "dist\\Swell-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\\Swell"

Section "Install"
  SetOutPath "$INSTDIR"
  ; Optional installer payload from Windows package build output.
  File /r "dist\\windows-x64\\Swell\\*.*"
  IfFileExists "$INSTDIR\\${APP_EXE}" +2 0
    Abort "Install payload missing executable: $INSTDIR\\${APP_EXE}"
  IfFileExists "$INSTDIR\\swell_doc_icon.ico" +2 0
    Abort "Install payload missing icon: $INSTDIR\\swell_doc_icon.ico"

  WriteRegStr HKCU "Software\\Classes\\.swell" "" "${APP_PROG_ID}"
  ; Keep legacy .sdproj association so SDApp-era projects continue to open in Swell.
  WriteRegStr HKCU "Software\\Classes\\.sdproj" "" "${APP_PROG_ID}"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}" "" "Swell Project"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}\\DefaultIcon" "" "$INSTDIR\\swell_doc_icon.ico"
  WriteRegStr HKCU "Software\\Classes\\${APP_PROG_ID}\\shell\\open\\command" "" '"$INSTDIR\\${APP_EXE}" "%1"'
  System::Call 'shell32::SHChangeNotify(i 0x8000000, i 0, p 0, p 0)'
SectionEnd

Section "Uninstall"
  DeleteRegKey HKCU "Software\\Classes\\${APP_PROG_ID}"
  DeleteRegValue HKCU "Software\\Classes\\.swell" ""
  DeleteRegValue HKCU "Software\\Classes\\.sdproj" ""
SectionEnd
