$ErrorActionPreference = 'Stop'
$relayConfig = Join-Path $env:USERPROFILE '.ssh/testbed-relay.conf'
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'relay.ssh_config') -Destination $relayConfig
$relayUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$relaySettings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$relayTrigger = New-ScheduledTaskTrigger -AtLogOn -User $relayUser
$relayRepeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 1)
$relayPrincipal = New-ScheduledTaskPrincipal -UserId $relayUser `
    -LogonType Interactive -RunLevel Limited
foreach ($relayHost in @('testbed-yanglab', 'testbed-ibn3090')) {
    $relayAction = New-ScheduledTaskAction -Execute 'C:\Windows\System32\OpenSSH\ssh.exe' `
        -Argument ('-NT -F "' + $relayConfig + '" ' + $relayHost) `
        -WorkingDirectory $env:USERPROFILE
    Register-ScheduledTask -TaskName "TestbedRelay-$relayHost" `
        -Action $relayAction -Trigger @($relayTrigger,$relayRepeat) -Settings $relaySettings `
        -Principal $relayPrincipal -Force
}
