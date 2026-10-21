$ErrorActionPreference = 'Stop'
foreach ($relayHost in @('testbed-yanglab', 'testbed-ibn3090')) {
    Disable-ScheduledTask -TaskName "TestbedRelay-$relayHost" | Out-Null
    Stop-ScheduledTask -TaskName "TestbedRelay-$relayHost"
}
