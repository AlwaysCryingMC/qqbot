' Launch QQ group bot in background (no CMD window). Logs -> bot.log
' Stop the bot: double-click 停止.bat
Set ws = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
ws.CurrentDirectory = dir
flagFile = dir & "\stop.flag"

Do
    ' Delete stale flag from previous run
    If fso.FileExists(flagFile) Then fso.DeleteFile flagFile

    ' 设置 UTF-8，避免 print ✓/emoji 时 GBK 编码崩溃死循环 (与 bot.py 内的 reconfigure 互为保险)
    exitCode = ws.Run("cmd /c set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && py bot.py >> bot.log 2>&1", 0, True)

    ' Check if user requested stop
    If fso.FileExists(flagFile) Then
        fso.DeleteFile flagFile
        Exit Do
    End If

    ' Exit code 0 = intentional shutdown, don't restart
    If exitCode = 0 Then Exit Do

    ' Otherwise (crash/reload) -> restart after 3s
    WScript.Sleep 3000
Loop
