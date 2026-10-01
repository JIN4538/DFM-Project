param(
    [Parameter(Mandatory=$true)][string]$InputDocx,
    [Parameter(Mandatory=$true)][string]$OutputPdf
)
$ErrorActionPreference = 'Stop'
$taskInput = (Resolve-Path -LiteralPath $InputDocx).Path
$taskOutput = [System.IO.Path]::GetFullPath($OutputPdf)
if ([System.IO.Path]::GetExtension($taskOutput) -ne '.pdf') { throw 'OutputPdf must end in .pdf' }
New-Item -ItemType Directory -Path ([System.IO.Path]::GetDirectoryName($taskOutput)) -Force | Out-Null
$taskBeforeHash = (Get-FileHash -LiteralPath $taskInput -Algorithm SHA256).Hash
$taskWord = $null
$taskDocument = $null
$taskUpdateLinks = $null
try {
    $taskWord = New-Object -ComObject Word.Application
    $taskWord.Visible = $false
    $taskWord.DisplayAlerts = 0
    $taskWord.AutomationSecurity = 3
    $taskUpdateLinks = $taskWord.Options.UpdateLinksAtOpen
    $taskWord.Options.UpdateLinksAtOpen = $false
    $taskDocument = $taskWord.Documents.Open($taskInput, $false, $true, $false)
    $taskDocument.Repaginate()
    $taskPages = $taskDocument.ComputeStatistics(2)
    $taskDocument.ExportAsFixedFormat($taskOutput, 17, $false, 0, 0)
    Write-Output ('Rendered pages: ' + $taskPages)
    Write-Output ('PDF: ' + $taskOutput)
} finally {
    if ($null -ne $taskDocument) {
        $taskDocument.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskDocument)
    }
    if ($null -ne $taskWord) {
        if ($null -ne $taskUpdateLinks) { $taskWord.Options.UpdateLinksAtOpen = $taskUpdateLinks }
        if ($taskWord.Documents.Count -eq 0) { $taskWord.Quit() }
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskWord)
    }
}
$taskAfterHash = (Get-FileHash -LiteralPath $taskInput -Algorithm SHA256).Hash
if ($taskBeforeHash -ne $taskAfterHash) { throw 'Source DOCX changed during read-only export' }
Write-Output ('Source unchanged SHA256: ' + $taskAfterHash)
