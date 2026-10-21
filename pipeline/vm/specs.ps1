# specs.ps1: print a VM host's specs for CG setup. Run in Windows PowerShell (no admin needed):
#   powershell -ExecutionPolicy Bypass -File specs.ps1
# Paste the whole output back. It prints no machine name, and your user name is masked in paths.
$ErrorActionPreference = "SilentlyContinue"
$u = $env:USERNAME
function Mask($s) { if ($s) { ($s -replace [regex]::Escape($u), "<user>") } }

"== Windows"
$os = Get-CimInstance Win32_OperatingSystem
"$($os.Caption) $($os.Version) build $($os.BuildNumber)"
"== CPU"
Get-CimInstance Win32_Processor | ForEach-Object { "$($_.Name.Trim()) | cores $($_.NumberOfCores) | logical $($_.NumberOfLogicalProcessors) | virtualization in firmware: $($_.VirtualizationFirmwareEnabled)" }
"== Memory"
"total {0:N1} GB, free {1:N1} GB" -f ($os.TotalVisibleMemorySize / 1MB), ($os.FreePhysicalMemory / 1MB)
"== Drives (free space is what WSL's disk file can still grow into)"
Get-PSDrive -PSProvider FileSystem | ForEach-Object {
  if ($_.Used -ne $null) { "{0}: used {1:N0} GB, free {2:N0} GB" -f $_.Name, ($_.Used / 1GB), ($_.Free / 1GB) } }
Get-PhysicalDisk | ForEach-Object { "disk: $($_.FriendlyName) | $($_.MediaType) | {0:N0} GB" -f ($_.Size / 1GB) }
"== WSL"
wsl --version 2>&1 | Out-String | ForEach-Object { $_ -replace "`0", "" }
wsl -l -v 2>&1 | Out-String | ForEach-Object { $_ -replace "`0", "" }
"== WSL disk files (ext4.vhdx)"
$roots = @("$env:LOCALAPPDATA\Packages", "$env:LOCALAPPDATA\wsl", "C:\WSL", "D:\WSL", "E:\WSL")
foreach ($r in $roots) {
  Get-ChildItem -Path $r -Recurse -Filter ext4.vhdx -ErrorAction SilentlyContinue | ForEach-Object {
    "{0}  {1:N1} GB" -f (Mask $_.FullName), ($_.Length / 1GB) } }
"== .wslconfig"
$wc = "$env:USERPROFILE\.wslconfig"
if (Test-Path $wc) { Get-Content $wc } else { "(none)" }
"== Power (0 = never sleep on AC)"
powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 2>$null | Select-String "Current AC Power Setting Index"
"== Other software"
"Docker Desktop: $(if (Get-Command 'Docker Desktop.exe' -ErrorAction SilentlyContinue -or (Test-Path "$env:ProgramFiles\Docker\Docker")) {'installed'} else {'not found'})"
"Tailscale on Windows: $(if (Test-Path "$env:ProgramFiles\Tailscale") {'installed'} else {'not found'})"
"== Network (download test, about 100 MB)"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$out = "$env:TEMP\cg-speed.bin"
$urls = @("https://speed.cloudflare.com/__down?bytes=100000000", "https://proof.ovh.net/files/100Mb.dat", "http://speedtest.tele2.net/100MB.zip")
$done = $false
foreach ($u2 in $urls) {
  try {
    $t = Measure-Command { Invoke-WebRequest -UseBasicParsing -UserAgent "Mozilla/5.0" -Uri $u2 -OutFile $out -ErrorAction Stop }
    "about {0:N0} Mbit/s ({1})" -f ((Get-Item $out).Length * 8 / 1e6 / $t.TotalSeconds), ([uri]$u2).Host
    $done = $true; break
  } catch { "  {0}: {1}" -f ([uri]$u2).Host, $_.Exception.Message }
  finally { Remove-Item $out -ErrorAction SilentlyContinue }
}
if (-not $done) { "download test failed on every test server" }
