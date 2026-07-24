# All Eye - PowerShell gunluk hook'u
# Her komutun metnini, dizinini, suresini, cikis kodunu VE ciktisini kaydeder.
# Cikti yakalama Start-Transcript uzerinden yapilir: prompt her calistiginda
# transcript dosyasindaki yeni bayt araligi = az onceki komutun ciktisi.
# Windows PowerShell 5.1 ve PowerShell 7+ ile uyumlu.

if ($env:ALLEYE_HOOK_LOADED -eq '1') { return }
$env:ALLEYE_HOOK_LOADED = '1'

$global:AllEyeCmd        = @@ALLEYE_CMD@@
$global:AllEyeHome       = if ($env:ALLEYE_HOME) { $env:ALLEYE_HOME } else { Join-Path $env:LOCALAPPDATA 'AllEye' }
$global:AllEyeJournal    = Join-Path $global:AllEyeHome 'journal.jsonl'
$global:AllEyeSession    = ([guid]::NewGuid().ToString('N')).Substring(0, 12)
$global:AllEyeTranscript = Join-Path $global:AllEyeHome ('transcripts\' + $global:AllEyeSession + '.log')
$global:AllEyeOffset     = 0
$global:AllEyeLastId     = 0
$global:AllEyeLastLec    = $null
$global:AllEyeMaxOut     = 20000
$global:AllEyeUtf8       = New-Object System.Text.UTF8Encoding $false

New-Item -ItemType Directory -Force -Path (Join-Path $global:AllEyeHome 'transcripts') | Out-Null

try {
    $tsArgs = @{ Path = $global:AllEyeTranscript; Force = $true }
    if ((Get-Command Start-Transcript).Parameters.ContainsKey('UseMinimalHeader')) {
        $tsArgs['UseMinimalHeader'] = $true
    }
    Start-Transcript @tsArgs *> $null
    $global:AllEyeTranscriptOn = $true
} catch {
    # Transcript acilamadi (baska bir transcript aktif olabilir):
    # komutlar yine kaydedilir, sadece cikti yakalanamaz.
    $global:AllEyeTranscriptOn = $false
}

Register-EngineEvent PowerShell.Exiting -SupportEvent -Action {
    try { Stop-Transcript *> $null } catch { }
} | Out-Null


function global:AllEye-Length {
    if (-not $global:AllEyeTranscriptOn) { return 0 }
    try { return (Get-Item -LiteralPath $global:AllEyeTranscript -ErrorAction Stop).Length }
    catch { return $global:AllEyeOffset }
}

function global:AllEye-Slice([long]$From, [long]$To) {
    if (-not $global:AllEyeTranscriptOn -or $To -le $From) { return '' }
    $len = [int][Math]::Min($To - $From, $global:AllEyeMaxOut)
    $start = $To - $len
    $fs = $null
    try {
        $fs = New-Object System.IO.FileStream(
            $global:AllEyeTranscript,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Read,
            [System.IO.FileShare]::ReadWrite)
        [void]$fs.Seek($start, [System.IO.SeekOrigin]::Begin)
        $buf = New-Object byte[] $len
        $read = $fs.Read($buf, 0, $len)
        return [System.Text.Encoding]::UTF8.GetString($buf, 0, $read)
    } catch {
        return ''
    } finally {
        if ($fs) { $fs.Dispose() }
    }
}

function global:AllEye-Record([bool]$Ok, $Lec) {
    $end = AllEye-Length
    $h = Get-History -Count 1
    if ($h -and $h.Id -gt $global:AllEyeLastId) {
        $global:AllEyeLastId = $h.Id
        $cmd = $h.CommandLine
        # Kendi cagrilarimizi kaydetme - geri besleme dongusu olusur.
        if ($cmd -notmatch '^\s*(alleye|ae)\b' -and $cmd -notmatch '(?i)\b(py|python3?)\b[^\|]*-m\s+alleye') {
            $out = AllEye-Slice $global:AllEyeOffset $end
            if ($out) {
                # Transcript'in ilk satiri prompt + komut yankisidir - ama SADECE
                # gercekten komutu iceriyorsa at. Korlemesine atarsak tek satirlik
                # hata mesajlarini (en degerli sey) kaybederiz.
                $lines = @($out -split "`r?`n")
                $head = ($cmd -split "`r?`n")[0].Trim()
                while ($lines.Count -gt 0 -and $head -and
                       ($lines[0].Contains($head) -or $lines[0].TrimStart().StartsWith('>>'))) {
                    $lines = @($lines[1..($lines.Count - 1)])
                }
                $out = ($lines -join "`n").Trim()
            }
            $truncated = ($out.Length -ge $global:AllEyeMaxOut)

            # Cikis kodu: $LASTEXITCODE cmdlet'ler tarafindan GUNCELLENMEZ, yani
            # bir cmdlet hatasindan sonra onceki native komuttan kalma bayat bir
            # deger okunabilir. Sadece degistiyse ya da komut gercekten harici bir
            # program ise ona guveniyoruz.
            $exit = 0
            if (-not $Ok) {
                $exit = 1
                $fresh = ($null -ne $Lec) -and ($Lec -ne $global:AllEyeLastLec)
                if (-not $fresh -and ($null -ne $Lec) -and ($Lec -ne 0)) {
                    $tok = @($cmd -split '\s+' | Where-Object { $_ })[0]
                    try {
                        if ((Get-Command $tok -ErrorAction SilentlyContinue).CommandType -eq 'Application') {
                            $fresh = $true
                        }
                    } catch { }
                }
                if ($fresh -and ($null -ne $Lec) -and ($Lec -ne 0)) { $exit = [int]$Lec }
            }

            $dur = 0
            try { $dur = [int](($h.EndExecutionTime - $h.StartExecutionTime).TotalMilliseconds) } catch { }

            $rec = [ordered]@{
                ts        = [Math]::Round(((Get-Date).ToUniversalTime() - [datetime]'1970-01-01').TotalSeconds, 3)
                session   = $global:AllEyeSession
                shell     = 'powershell'
                cwd       = (Get-Location).Path
                cmd       = $cmd
                exit      = $exit
                dur_ms    = $dur
                out       = $out
                truncated = $truncated
            }
            try {
                $json = $rec | ConvertTo-Json -Compress -Depth 3
                [System.IO.File]::AppendAllText($global:AllEyeJournal, $json + "`n", $global:AllEyeUtf8)
            } catch { }
        }
    }
    $global:AllEyeOffset = $end
    $global:AllEyeLastLec = $Lec
}

# Mevcut prompt'u koru, ustune bindirme yap (posh-git, oh-my-posh vs. bozulmasin).
if (-not (Test-Path Function:\AllEyeInnerPrompt)) {
    if (Test-Path Function:\prompt) {
        Set-Item -Path Function:\AllEyeInnerPrompt -Value (Get-Item Function:\prompt).ScriptBlock
    } else {
        Set-Item -Path Function:\AllEyeInnerPrompt -Value { 'PS ' + (Get-Location).Path + '> ' }
    }
}

function global:prompt {
    $ok  = $?
    $lec = $global:LASTEXITCODE
    try { AllEye-Record $ok $lec } catch { }
    $global:LASTEXITCODE = $lec
    AllEyeInnerPrompt
}

# Kisayol: takildiginda sadece `ae` yaz.
function global:ae {
    $exe = $global:AllEyeCmd[0]
    $pre = @()
    if ($global:AllEyeCmd.Count -gt 1) { $pre = $global:AllEyeCmd[1..($global:AllEyeCmd.Count - 1)] }
    & $exe @pre @args
}

$h0 = Get-History -Count 1
if ($h0) { $global:AllEyeLastId = $h0.Id }
$global:AllEyeOffset = AllEye-Length
