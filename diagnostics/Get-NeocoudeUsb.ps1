#requires -Version 5.1
<# Metadata only. Never opens a COM port, changes drivers or sends USB commands. #>
[CmdletBinding()]
param([string]$OutputPath)
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
$report=[ordered]@{schema_version=1; kind='usb_inventory'; tool_version='0.3.0';
    collected_at=[DateTime]::UtcNow.ToString('o'); read_only=$true;
    scope=@{observer=$env:COMPUTERNAME}; status='ok'; serial_ports=@(); usb_devices=@(); network_adapters=@(); network_addresses=@(); error=$null;
    note='Metadata only. A COM port does not prove an RS-485 adapter or the connected PLC. No serial port opened.'}
try {
    $report.serial_ports=@(Get-CimInstance -ClassName Win32_SerialPort -OperationTimeoutSec 5 |
        Select-Object DeviceID,Name,Status,PNPDeviceID)
    $report.usb_devices=@(Get-CimInstance -ClassName Win32_PnPEntity -Filter "PNPDeviceID LIKE 'USB%'" -OperationTimeoutSec 5 |
        Select-Object -First 100 Name,Status,PNPClass,PNPDeviceID)
    $report.network_adapters=@(Get-CimInstance -ClassName Win32_NetworkAdapter -Filter "PhysicalAdapter=True" -OperationTimeoutSec 5 |
        Select-Object -First 30 Name,NetConnectionID,NetConnectionStatus,PNPDeviceID,Index)
    $report.network_addresses=@(Get-CimInstance -ClassName Win32_NetworkAdapterConfiguration -Filter "IPEnabled=True" -OperationTimeoutSec 5 |
        Select-Object -First 30 Description,Index,IPAddress,IPSubnet,DefaultIPGateway)
} catch { $report.status='partial'; $report.error=$_.Exception.GetBaseException().Message }
if ($OutputPath) {
    $path=[IO.Path]::GetFullPath($OutputPath)
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($path))
    $file=[IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $writer=New-Object IO.StreamWriter($file,(New-Object Text.UTF8Encoding($false)))
    try { $writer.WriteLine(($report | ConvertTo-Json -Depth 8)) } finally { $writer.Dispose() }
    Write-Host ('Inventory saved: ' + $path)
} else { $report | ConvertTo-Json -Depth 8 }
