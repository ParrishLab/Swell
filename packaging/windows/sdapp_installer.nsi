Unicode true
RequestExecutionLevel user

!define APP_NAME "SDApp"
!define APP_VERSION "0.1.3"
!define APP_EXE "SDApp.exe"
!define APP_PROG_ID "SDApp.Project"

OutFile "dist\\SDApp-Setup-${APP_VERSION}.exe"
InstallDir "$LOCALAPPDATA\\SDApp"

Section "Install"
  SetOutPath "$INSTDIR"
  ; Optional installer payload from Windows package build output.
  File /r "dist\\windows-x64\\SDApp\\*.*"
  IfFileExists "$INSTDIR\\${APP_EXE}" +2 0
    Abort "Install payload missing executable: $INSTDIR\\${APP_EXE}"
  IfFileExists "$INSTDIR\\sdproj_doc_icon.ico" +2 0
    Abort "Install payload missing icon: $INSTDIR\\sdproj_doc_icon.ico"

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
