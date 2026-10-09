$prototypeRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonRuntime = 'C:\Users\Andrei\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

Start-Process -FilePath $pythonRuntime -ArgumentList '-m','http.server','4173','--bind','127.0.0.1' -WorkingDirectory $prototypeRoot -WindowStyle Hidden
Start-Sleep -Milliseconds 700
Start-Process 'http://127.0.0.1:4173/'
