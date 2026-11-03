' Strat-O-Matic Card Maker - quiet launcher.
'
' Double-click this file to start the app. It checks that Python and Flask
' are ready, then starts start_windows.bat in a MINIMIZED window (it sits
' on the taskbar; close it to stop the app) and your browser opens by
' itself. If something needs attention (Python missing, first-time Flask
' install) the window opens normally instead, so you can read it.

Option Explicit
Dim shell, fso, scriptDir, batFile, py

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batFile = fso.BuildPath(scriptDir, "start_windows.bat")

If Not fso.FileExists(batFile) Or Not fso.FileExists(fso.BuildPath(scriptDir, "app.py")) Then
    MsgBox "The card maker's files aren't next to this launcher." & vbCrLf & vbCrLf & _
           "If you opened it from inside the downloaded ZIP file, first right-click " & _
           "the ZIP, choose ""Extract All"", and start it from the extracted folder.", _
           vbExclamation, "Strat-O-Matic Card Maker"
    WScript.Quit 1
End If

shell.CurrentDirectory = scriptDir

' Run a command hidden and wait for it; True when it succeeds.
Function Works(cmd)
    Works = (shell.Run("cmd /c " & cmd & " >nul 2>&1", 0, True) = 0)
End Function

py = ""
If Works("py -3 -c ""import sys; sys.exit(sys.version_info < (3, 9))""") Then
    py = "py -3"
ElseIf Works("python -c ""import sys; sys.exit(sys.version_info < (3, 9))""") Then
    py = "python"
End If

If py <> "" And Works(py & " -c ""import flask""") Then
    ' All set: start minimized (7 = minimized, not focused).
    shell.Run """" & batFile & """", 7, False
Else
    ' Show the window so its messages (or the Flask install) can be read.
    shell.Run """" & batFile & """", 1, False
End If
