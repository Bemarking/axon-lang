$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

$Exe = Join-Path $RepoRoot 'build\pyinstaller\dist\axon\axon.exe'

function Invoke-Case {
    param(
        [string]$Name,
        [scriptblock]$Action,
        [int]$ExpectedExit,
        [string[]]$ExpectedContains
    )

    $output = & $Action 2>&1 | Out-String
    $exitCode = $LASTEXITCODE

    if ($exitCode -ne $ExpectedExit) {
        throw "$Name failed: expected exit $ExpectedExit but got $exitCode`n$output"
    }

    foreach ($expected in $ExpectedContains) {
        if ($output -notmatch [regex]::Escape($expected)) {
            throw "$Name failed: output missing '$expected'`n$output"
        }
    }

    Write-Output "PASS: $Name"
}

$BadSource = Join-Path $RepoRoot 'temp_a8_bad.axon'
Set-Content -Path $BadSource -Value '42 + garbage' -Encoding UTF8

Invoke-Case -Name 'check-missing-file' -Action { & $Exe check 'examples/__missing__.axon' --no-color } -ExpectedExit 2 -ExpectedContains @(
    'File not found: examples/__missing__.axon'
)

Invoke-Case -Name 'compile-missing-file' -Action { & $Exe compile 'examples/__missing__.axon' } -ExpectedExit 2 -ExpectedContains @(
    'File not found: examples/__missing__.axon'
)

Invoke-Case -Name 'compile-invalid-syntax' -Action { & $Exe compile $BadSource } -ExpectedExit 1 -ExpectedContains @(
    'temp_a8_bad.axon:1:1',
    'Unexpected token at top level'
)

Invoke-Case -Name 'trace-invalid-json' -Action { & $Exe trace 'README.md' --no-color } -ExpectedExit 2 -ExpectedContains @(
    'Invalid JSON: Expecting value: line 1 column 1 (char 0)'
)

Invoke-Case -Name 'check-missing-argument' -Action { & $Exe check } -ExpectedExit 2 -ExpectedContains @(
    'usage: axon check',
    'the following arguments are required: file'
)

Invoke-Case -Name 'unknown-command' -Action { & $Exe unknown } -ExpectedExit 2 -ExpectedContains @(
    "invalid choice: 'unknown'",
    '{check,compile,trace,version}'
)

Write-Output 'AXON MVP packaged error contract validated.'