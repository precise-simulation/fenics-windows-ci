param(
    [Parameter(Mandatory = $true)]
    [string]$Prefix
)

$root = Join-Path $Prefix 'Library'
$metadata = @(
    Join-Path $root 'lib\pkgconfig\PETSc.pc'
    Join-Path $root 'lib\petsc'
    Join-Path $root 'share\petsc'
)
$patterns = [System.Collections.Generic.List[string]]::new()
$patterns.Add('(?i)/cygdrive/[^\r\n]*(?:[\\/]bld[\\/]|[\\/]build(?:_env)?[\\/]|[\\/]src[\\/]|[\\/]source[\\/]|[\\/]work[\\/]|[\\/]h_env(?:[\\/]|$))')
$patterns.Add('(?i)[A-Z]:[\\/][^\r\n]*[\\/](?:bld|build(?:_env)?|src|source|work|h_env)(?:[\\/]|$)')
$patterns.Add('(?i)/(?:home|opt|tmp)/[^\r\n]*/(?:bld|build(?:_env)?|src|source|work|h_env)(?:/|$)')

foreach ($name in 'SRC_DIR', 'BUILD_PREFIX', 'RECIPE_DIR', 'WORK_DIR') {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) {
        $patterns.Add([regex]::Escape($value))
    }
}

$files = foreach ($path in $metadata) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Missing installed metadata path: $path"
    }
    if ((Get-Item -LiteralPath $path).PSIsContainer) {
        Get-ChildItem -LiteralPath $path -Recurse -File
    } else {
        Get-Item -LiteralPath $path
    }
}

$leaks = foreach ($file in $files) {
    $bytes = [IO.File]::ReadAllBytes($file.FullName)
    if ($bytes -contains [byte]0) {
        continue
    }
    $text = [Text.Encoding]::UTF8.GetString($bytes)
    foreach ($pattern in $patterns) {
        if ([regex]::IsMatch($text, $pattern)) {
            [PSCustomObject]@{ File = $file.FullName; Pattern = $pattern }
            break
        }
    }
}

if ($leaks) {
    $leaks | Format-Table -AutoSize | Out-String | Write-Error
    exit 1
}
