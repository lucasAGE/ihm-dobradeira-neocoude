#requires -Version 5.1
<# Offline maintenance probe. No commands are sent to the application/PLC.
   WebSocket receives state only; HTTP retrieves headers without executing HTML.
   Run from a normal PowerShell session on the maintenance notebook. #>
[CmdletBinding()]
param(
    [string]$TargetAddress = '192.168.50.1',
    [ValidateCount(1,12)][int[]]$Ports = @(22,80,8080,8765),
    [ValidateRange(100,10000)][int]$TimeoutMs = 1500,
    [ValidateRange(1,65535)][int]$HttpPort = 8080,
    [ValidateRange(1,65535)][int]$WebSocketPort = 8765,
    [ValidateRange(0,60)][int]$WebSocketSeconds = 10,
    [string]$OutputPath = (Join-Path $PSScriptRoot ('output\windows-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.json'))
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$parsedAddress = $null
if (-not [Net.IPAddress]::TryParse($TargetAddress, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork) {
    throw 'TargetAddress must be an IPv4 address.'
}
if (@($Ports | Where-Object { $_ -lt 1 -or $_ -gt 65535 }).Count) { throw 'Invalid TCP port.' }
if (Test-Path -LiteralPath $OutputPath) { throw 'Output already exists. Use a new filename.' }

function Get-UtcTimestamp { [DateTime]::UtcNow.ToString('o') }

function Test-TcpPort([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $result = [ordered]@{ port=$Port; collected_at=(Get-UtcTimestamp); status='error'; duration_ms=0; error=$null }
    $pending = $null
    try {
        $pending = $client.BeginConnect($TargetAddress,$Port,$null,$null)
        if (-not $pending.AsyncWaitHandle.WaitOne($TimeoutMs)) { $result.status='timeout' }
        else { $client.EndConnect($pending); $result.status='open' }
    } catch {
        $cause=$_.Exception.GetBaseException()
        $result.error=$cause.Message
        if ($cause -is [Net.Sockets.SocketException] -and $cause.SocketErrorCode -eq 'ConnectionRefused') {
            $result.status='refused'
        }
    } finally {
        $client.Dispose()
        if ($null -ne $pending) { $pending.AsyncWaitHandle.Close() }
        $result.duration_ms=[math]::Round($watch.Elapsed.TotalMilliseconds,2)
    }
    return $result
}

function Get-LocalCommand([string]$FileName,[string]$Arguments) {
    $process = New-Object Diagnostics.Process
    $process.StartInfo = New-Object Diagnostics.ProcessStartInfo
    $process.StartInfo.FileName=$FileName
    $process.StartInfo.Arguments=$Arguments
    $process.StartInfo.UseShellExecute=$false
    $process.StartInfo.CreateNoWindow=$true
    $process.StartInfo.RedirectStandardOutput=$true
    $process.StartInfo.RedirectStandardError=$true
    try {
        [void]$process.Start()
        $stdout=$process.StandardOutput.ReadToEndAsync()
        $stderr=$process.StandardError.ReadToEndAsync()
        if (-not $process.WaitForExit(3000)) { $process.Kill(); return @{status='timeout'} }
        $text=$stdout.GetAwaiter().GetResult() + $stderr.GetAwaiter().GetResult()
        return @{status=$(if($process.ExitCode -eq 0){'ok'}else{'error'}); output=$text.Substring(0,[math]::Min(65536,$text.Length)); truncated=($text.Length -gt 65536)}
    } catch { return @{status='unavailable'; error=$_.Exception.GetBaseException().Message} }
    finally { $process.Dispose() }
}

function Receive-State {
    $result = [ordered]@{ status='not_collected'; connected=$false; frames=@(); messages=0; malformed=0;
        started_at=(Get-UtcTimestamp); elapsed_seconds=0; error=$null;
        successful_encoder_read_hz=$null; rtu_latency_ms=$null;
        note='Receive only. Message rate and poll_count do not prove successful encoder reads or RTU latency.' }
    if ($WebSocketSeconds -eq 0) { return $result }
    $socket = New-Object Net.WebSockets.ClientWebSocket
    $socket.Options.Proxy=$null
    $cancel = New-Object Threading.CancellationTokenSource
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $frames = New-Object 'Collections.Generic.List[object]'
    $stream = New-Object IO.MemoryStream
    $totalBytes=0
    try {
        $cancel.CancelAfter($TimeoutMs)
        $uri=[Uri]('ws://{0}:{1}/' -f $TargetAddress,$WebSocketPort)
        [void]$socket.ConnectAsync($uri,$cancel.Token).GetAwaiter().GetResult()
        $result.connected=$true
        $result.status='connected'
        $cancel.CancelAfter($WebSocketSeconds * 1000)
        $buffer=New-Object byte[] 8192
        $segment=New-Object 'ArraySegment[byte]' -ArgumentList @(,$buffer)
        while ($socket.State -eq [Net.WebSockets.WebSocketState]::Open -and $frames.Count -lt 600) {
            try { $received=$socket.ReceiveAsync($segment,$cancel.Token).GetAwaiter().GetResult() }
            catch {
                if ($cancel.IsCancellationRequested) { $result.status='observation_complete'; break }
                throw
            }
            if ($received.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) {
                $result.status='closed_by_server'; break
            }
            $totalBytes += $received.Count
            if ($totalBytes -gt 2097152) { $result.status='byte_limit'; break }
            if ($stream.Length + $received.Count -gt 65536) { $result.status='message_too_large'; break }
            $stream.Write($buffer,0,$received.Count)
            if (-not $received.EndOfMessage) { continue }
            $result.messages++
            if ($received.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Text) {
                try {
                    $message=[Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
                    if ($message.type -in @('full_state','state_update')) {
                        $state=[ordered]@{}
                        foreach ($name in @('encoder_raw','encoder_pulses','encoder_degrees','encoder_moving',
                            'encoder_degrees_disco','encoder_direction','modbus_connected','poll_count','last_update',
                            'timestamp','angles','target_angle','heartbeat','inputs','outputs','states','control_bits',
                            'dobra_atual','contador_pecas','velocidade_rpm','machine_state_name','machine_state_address',
                            'machine_state_error','read_quality','feedback_version','feedback_session','poll_ok')) {
                            if ($message.data.PSObject.Properties.Name -contains $name) { $state[$name]=$message.data.$name }
                        }
                        $frames.Add(@{received_at=(Get-UtcTimestamp); elapsed_ms=$watch.Elapsed.TotalMilliseconds; type=$message.type; data=$state})
                    }
                } catch { $result.malformed++ }
            }
            $stream.SetLength(0)
            $stream.Position=0
        }
        if ($frames.Count -ge 600) { $result.status='sample_limit' }
    } catch {
        $result.status=$(if($cancel.IsCancellationRequested){'timeout'}else{'error'})
        $result.error=$_.Exception.GetBaseException().Message
    } finally {
        $result.elapsed_seconds=[math]::Round($watch.Elapsed.TotalSeconds,3)
        $result.frames=@($frames.ToArray())
        # Abort does not send application data or require a blocking close handshake.
        $socket.Abort(); $socket.Dispose(); $cancel.Dispose(); $stream.Dispose()
    }
    return $result
}

$report=[ordered]@{schema_version=1; kind='windows_probe'; tool_version='0.3.0'; collected_at=(Get-UtcTimestamp);
    read_only=$true; scope=@{target=$TargetAddress; observer=$env:COMPUTERNAME; platform=$PSVersionTable.PSVersion.ToString()};
    checks=[ordered]@{}; limitations=@(
        'Ping/TCP tests do not identify a Raspberry Pi or certify the machine.',
        'Connection refused means a TCP rejection: inspect SSH listener, service and firewall on the target.',
        'No SSH authentication, application commands, register writes or automatic reconnection.',
        'Reports contain private network identifiers. Review before sharing.')}
$ping=New-Object Net.NetworkInformation.Ping
try {
    $reply=$ping.Send($TargetAddress,$TimeoutMs)
    $report.checks.ping=@{status=$reply.Status.ToString(); roundtrip_ms=$reply.RoundtripTime; collected_at=(Get-UtcTimestamp)}
} catch { $report.checks.ping=@{status='error'; error=$_.Exception.GetBaseException().Message} }
finally { $ping.Dispose() }
$report.checks.tcp=@($Ports | Select-Object -Unique | ForEach-Object { Test-TcpPort $_ })
$response=$null
try {
    $request=[Net.HttpWebRequest]::Create(('http://{0}:{1}/' -f $TargetAddress,$HttpPort))
    $request.Timeout=$TimeoutMs; $request.ReadWriteTimeout=$TimeoutMs
    $request.AllowAutoRedirect=$false; $request.Proxy=$null; $request.Method='GET'
    $response=$request.GetResponse()
    $report.checks.http=@{status='responded'; status_code=[int]$response.StatusCode; content_type=$response.ContentType; port=$HttpPort}
} catch {
    $cause=$_.Exception.GetBaseException()
    if ($cause -is [Net.WebException] -and $null -ne $cause.Response) {
        $response=$cause.Response
        $report.checks.http=@{status='responded'; status_code=[int]$response.StatusCode; content_type=$response.ContentType; port=$HttpPort}
    } else {
        $report.checks.http=@{status='error'; error=$cause.Message; port=$HttpPort}
    }
} finally { if ($null -ne $response) { $response.Dispose() } }
$report.checks.websocket=Receive-State
$report.checks.ipconfig=Get-LocalCommand 'ipconfig.exe' '/all'
$report.checks.wifi=Get-LocalCommand 'netsh.exe' 'wlan show interfaces'
$report.checks.neighbors=Get-LocalCommand 'arp.exe' '-a'
$fullPath=[IO.Path]::GetFullPath($OutputPath)
[void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($fullPath))
$file=[IO.File]::Open($fullPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
$writer=New-Object IO.StreamWriter($file,(New-Object Text.UTF8Encoding($false)))
try { $writer.WriteLine(($report | ConvertTo-Json -Depth 16)) } finally { $writer.Dispose() }
Write-Host ('Report saved: ' + $fullPath)
Write-Host 'No machine movement or stop-limit validation performed.'
