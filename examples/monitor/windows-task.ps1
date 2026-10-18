# Example registration, run manually after editing these paths.
# Keep credentials in the task account's environment; never put them in arguments.
$monitorAction = New-ScheduledTaskAction `
    -Execute 'C:\Chatcheck\venv\Scripts\python.exe' `
    -Argument '-m chatcheck monitor --config C:\Chatcheck\clients\client.json --db C:\Chatcheck\data\monitor.sqlite3' `
    -WorkingDirectory 'C:\Chatcheck'
$monitorTrigger = New-ScheduledTaskTrigger -Daily -At '05:15'
# Example for Asia/Karachi: 05:15 local = 00:15 UTC. Match your local timezone.
$monitorSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable
Register-ScheduledTask -TaskName 'Chatcheck client monitoring' -Action $monitorAction `
    -Trigger $monitorTrigger -Settings $monitorSettings -Description 'One bounded monitoring cycle daily'
