$utf8NoBom = New-Object System.Text.UTF8Encoding $false

$timingLine = '^\s*(\d+:)?\d+:\d{2}\.\d{3}\s+-->'
$shortStamp = [regex]'(?<![\d:])(\d+):(\d{2}\.\d{3})'
$toFullStamp = [System.Text.RegularExpressions.MatchEvaluator]{
    param($m)
    $minutes = [int]$m.Groups[1].Value
    '{0:D2}:{1:D2}:{2}' -f [int][math]::Floor($minutes / 60), ($minutes % 60), $m.Groups[2].Value
}

foreach ($file in Get-ChildItem -Filter *.vtt -File) {
    if ($file.BaseName -like '*_converted') {
        Write-Host "Skipping already converted file $($file.Name)"
        continue
    }

    Write-Host "Processing $($file.Name)..."

    $out = Join-Path $file.DirectoryName "$($file.BaseName)_converted.vtt"
    $lines = @(Get-Content -LiteralPath $file.FullName -Encoding UTF8)

    $converted = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line.Trim() -eq '') { $line = '' }

        if ($line -match $timingLine) {
            $line = $shortStamp.Replace($line, $toFullStamp)

            # WebVTT needs a blank line before every cue
            $n = $converted.Count
            $prevBlank = $n -eq 0 -or $converted[$n - 1] -eq ''
            $prevIsId = -not $prevBlank -and $converted[$n - 1] -notlike 'WEBVTT*' -and
                ($n -eq 1 -or $converted[$n - 2] -eq '')
            if (-not $prevBlank -and -not $prevIsId) { $converted.Add('') }
        }
        $converted.Add($line)
    }

    if ($lines.Count -eq 0 -or $lines[0] -notlike 'WEBVTT*') {
        $converted.InsertRange(0, [string[]]@('WEBVTT', ''))
    }

    [System.IO.File]::WriteAllLines($out, $converted.ToArray(), $utf8NoBom)
}

Write-Host 'Done! New files are suffixed with _converted.vtt'
Read-Host 'Press Enter to continue'
