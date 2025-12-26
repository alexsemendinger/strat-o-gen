' Strat-O-Matic Card Generator - Hidden Launcher
' This script runs start_windows.bat without showing a console window
'
' Double-click this file to start the app!

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Get the directory where this script is located
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Path to the batch file
batFile = fso.BuildPath(scriptDir, "start_windows.bat")

' Check if batch file exists
If Not fso.FileExists(batFile) Then
    MsgBox "Error: Cannot find start_windows.bat" & vbCrLf & vbCrLf & _
           "Make sure this file is in the same folder as start_windows.bat", _
           vbCritical, "Strat-O-Gen Error"
    WScript.Quit 1
End If

' Run the batch file minimized (1 = minimized, 0 = hidden)
' Using 1 (minimized) so user can see the window if needed, but it starts out of the way
WshShell.Run """" & batFile & """", 1, False
