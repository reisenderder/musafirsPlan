param(
    [ValidateSet("init", "run", "doctor", "discover", "list", "audit", "import-manual")]
    [string]$Command = "run",
    [string]$PythonExecutable = "python",
    [string]$EnvFile = ".env"
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$previousLocation = Get-Location

try {
    Set-Location -LiteralPath $projectRoot
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    & $PythonExecutable -m musafirs_bot --env $EnvFile $Command
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    Set-Location -LiteralPath $previousLocation.Path
}
