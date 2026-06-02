' Donum Print Agent - hidden, auto-restarting launcher (runs as the logged-in user)
' Starts agent.py with no console window; if it ever exits, waits 5s and restarts.
Set sh  = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
sh.CurrentDirectory = fso.GetParentFolderName(WScript.ScriptFullName)
Do
    ' 0 = hidden window, True = wait until agent.py exits before looping
    sh.Run "pythonw.exe agent.py", 0, True
    WScript.Sleep 5000
Loop
