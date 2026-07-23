; EnPu NSIS installer hooks (Tauri 2)
; https://v2.tauri.app/distribute/windows-installer/

!macro NSIS_HOOK_POSTINSTALL
  ; Ship + run PaddleOCR setup (user-local venv under %LOCALAPPDATA%\EnPu)
  ; Script path: $INSTDIR\resources\install-paddle-ocr.ps1 (Tauri resources)
  DetailPrint "EnPu: launching PaddleOCR install script (optional OCR)..."
  ; Run visible PowerShell so user can see progress; non-blocking wait with timeout-friendly ExecWait
  nsExec::ExecToLog 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\resources\install-paddle-ocr.ps1"'
  Pop $0
  DetailPrint "EnPu: install-paddle-ocr.ps1 exit code $0"
  ; Also leave a desktop shortcut note if python missing (script logs to %LOCALAPPDATA%\EnPu)
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Do not remove %LOCALAPPDATA%\EnPu automatically (models are large / user data)
  DetailPrint "EnPu: leaving %LOCALAPPDATA%\EnPu (OCR venv) in place"
!macroend
