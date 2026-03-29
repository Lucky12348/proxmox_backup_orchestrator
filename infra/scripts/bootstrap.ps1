$root = Resolve-Path (Join-Path $PSScriptRoot "..\\..")
$envFile = Join-Path $root ".env"

if (-not (Test-Path $envFile)) {
    Write-Host ".env not found at $envFile"
    Write-Host "Copy .env.example to .env before starting local services."
    exit 1
}

$values = @{}

Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#" -or $_ -match "^\s*$") {
        return
    }

    $parts = $_ -split "=", 2
    if ($parts.Length -eq 2) {
        $values[$parts[0]] = $parts[1]
    }
}

$apiPort = if ($values.ContainsKey("API_PORT")) { $values["API_PORT"] } else { "8000" }
$webPort = if ($values.ContainsKey("WEB_PORT")) { $values["WEB_PORT"] } else { "5173" }

Write-Host "Environment file found: $envFile"
Write-Host "API: http://localhost:$apiPort/health"
Write-Host "Web: http://localhost:$webPort"
