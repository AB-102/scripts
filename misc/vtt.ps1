$utf8NoBom = New-Object System.Text.UTF8Encoding $false

foreach ($file in Get-ChildItem -Filter *.vtt -File) {
    # Skip files that already look converted
    if ($file.BaseName -like '*_converted') {
        Write-Host "Skipping already converted file $($file.Name)"
        continue
    }

    Write-Host "Processing $($file.Name)..."

    $out = Join-Path $file.DirectoryName "$($file.BaseName)_converted.vtt"
    $lines = @(Get-Content -LiteralPath $file.FullName -Encoding UTF8)

    $converted = @(foreach ($line in $lines) {
        # Check if line looks like a timestamp MM:SS.mmm --> MM:SS.mmm
        if ($line -match '^\d+:\d{2}\.\d{3}') {
            # Prefix 00: to both the start and end timestamps if they lack hours
            $line = $line -replace '(?<![\d:])(\d+:\d{2}\.\d{3})', '00:$1'
        }
        $line
    })

    # Add the WEBVTT header only if the source doesn't already have one
    if ($lines.Count -eq 0 -or $lines[0] -notlike 'WEBVTT*') {
        $converted = @('WEBVTT', '') + $converted
    }

    [System.IO.File]::WriteAllLines($out, [string[]]$converted, $utf8NoBom)
}

Write-Host 'Done! New files are suffixed with _converted.vtt'
Read-Host 'Press Enter to continue'
