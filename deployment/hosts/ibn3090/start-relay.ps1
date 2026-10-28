$ErrorActionPreference = 'Stop'
foreach ($relayHost in @('testbed-yanglab', 'testbed-ibn3090')) {
    Enable-ScheduledTask -TaskName "TestbedRelay-$relayHost" | Out-Null
    Start-ScheduledTask -TaskName "TestbedRelay-$relayHost"
}
