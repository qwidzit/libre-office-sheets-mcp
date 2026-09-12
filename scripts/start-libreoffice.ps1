<#
    Starts LibreOffice Calc with the UNO socket the MCP server connects to.

    The server can launch LibreOffice itself, so this is only needed if you
    prefer to start it by hand, or you want the socket on a non-default port.

    Usage:  powershell -ExecutionPolicy Bypass -File scripts\start-libreoffice.ps1
#>
param(
    [int]$Port = 2002,
    [string]$SofficePath = ""
)

if (-not $SofficePath) {
    $candidates = @(
        "C:\Program Files\LibreOffice\program\soffice.exe",
        "C:\Program Files (x86)\LibreOffice\program\soffice.exe"
    )
    $SofficePath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if (-not $SofficePath) {
    Write-Error "Could not find soffice.exe. Pass -SofficePath 'C:\path\to\soffice.exe'."
    exit 1
}

# Passing --accept to a second invocation hands it to the already-running
# instance, so this is safe to run whether or not LibreOffice is already open.
$accept = "--accept=socket,host=127.0.0.1,port=$Port;urp;"
Write-Host "Starting: $SofficePath --calc $accept"
Start-Process -FilePath $SofficePath -ArgumentList "--calc", $accept

Write-Host "LibreOffice Calc is starting with a UNO socket on port $Port."
