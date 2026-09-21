param([Parameter(Mandatory=$true)][string]$InputDocx, [Parameter(Mandatory=$true)][string]$OutputPdf)
$ErrorActionPreference='Stop'
$taskWord=$null
$taskDoc=$null
$taskLinks=$null
try {
    $taskWord=New-Object -ComObject Word.Application
    $taskWord.DisplayAlerts=0
    $taskWord.AutomationSecurity=3
    $taskLinks=$taskWord.Options.UpdateLinksAtOpen
    $taskWord.Options.UpdateLinksAtOpen=$false
    $taskDoc=$taskWord.Documents.Open($InputDocx,$false,$true,$false)
    $taskDoc.Repaginate()
    $taskPages=$taskDoc.ComputeStatistics(2)
    $taskDoc.ExportAsFixedFormat($OutputPdf,17,$false,1,0,1,1,0,$false,$false,1,$false,$false,$false)
    Write-Output ('Rendered pages: '+$taskPages)
} finally {
    if($null -ne $taskDoc) {
        $taskDoc.Close(0)
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskDoc)
    }
    if($null -ne $taskWord) {
        if($null -ne $taskLinks){$taskWord.Options.UpdateLinksAtOpen=$taskLinks}
        if($taskWord.Documents.Count -eq 0){$taskWord.Quit()}
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($taskWord)
    }
}
