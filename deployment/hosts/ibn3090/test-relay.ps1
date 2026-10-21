$ErrorActionPreference = 'Stop'
Get-ScheduledTask -TaskName 'TestbedRelay-*' | Format-Table TaskName, State -AutoSize
$snapshot = Invoke-RestMethod -TimeoutSec 20 `
    -Uri 'http://127.0.0.1:28181/v1/snapshots/latest?run_id=ibn3090-s2-20261008'
[pscustomobject]@{
    Run = $snapshot.run_id
    Snapshot = $snapshot.snapshot_id
    ObservedTo = $snapshot.observed_to
    Flows = $snapshot.flows.Count
    Sessions = $snapshot.sessions.Count
} | Format-List
