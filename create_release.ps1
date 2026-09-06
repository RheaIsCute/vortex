# GitHub Release Creation Script for Vortex v5.6.0
# This script creates a GitHub release and uploads the installer

param(
    [string]$Token = $env:GITHUB_TOKEN
)

# Configuration
$owner = "RheaIsCute"
$repo = "vortex"
$tag = "v5.6.0"
$releaseName = "Vortex v5.6.0 - In-Game Memory Reading"
$installerPath = "dist_installer\VortexSetup.exe"

# Release description
$body = "# Vortex v5.6.0 - In-Game Memory Reading Feature`n`n## WARNING`nThis release includes a memory reading feature that may violate Riot Games Terms of Service. Use at your own risk.`n`n## New Features`n- In-game memory reading with two modes`n- External Mode: Uses ReadProcessMemory (safer, requires offset updates)`n- Internal Mode: DLL injection (no offsets, extremely high ban risk)`n- Warning indicators throughout the UI`n- Mode selector in Settings > Advanced`n- Comprehensive documentation included`n`n## Technical Implementation`n- memory_reader.py: External memory reading with pattern scanning`n- injector.py: DLL injection engine using LoadLibrary technique`n- valorant_internal.cpp: C++ DLL source with game function hooking`n- Shared memory IPC for internal mode communication`n- Build script for compiling internal DLL`n`n## Documentation`n- MEMORY_READING.md - Usage guide`n- INTERNAL_VS_EXTERNAL.md - Technical deep dive`n`n## Installation`nDownload VortexSetup.exe below and run to install/update.`n`nPrevious release: v5.5.54"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  GitHub Release Creator for Vortex v5.6.0" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# Check if installer exists
if (-not (Test-Path $installerPath)) {
    Write-Host "ERROR: Installer not found at: $installerPath" -ForegroundColor Red
    exit 1
}

$installerSize = (Get-Item $installerPath).Length / 1MB
$installerSizeRounded = [math]::Round($installerSize, 2)
Write-Host "Installer found: $installerPath"
Write-Host "Size: $installerSizeRounded MB" -ForegroundColor Green

# Get GitHub token
if (-not $Token) {
    Write-Host ""
    Write-Host "GitHub Personal Access Token required." -ForegroundColor Yellow
    Write-Host "Create one at: https://github.com/settings/tokens" -ForegroundColor Yellow
    Write-Host "Required scope: repo" -ForegroundColor Yellow
    Write-Host ""
    $secureToken = Read-Host "Enter your GitHub token" -AsSecureString
    $Token = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken))
    
    if (-not $Token) {
        Write-Host "ERROR: Token is required" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "Creating release..." -ForegroundColor Cyan

# Create the release
$headers = @{
    "Authorization" = "token $Token"
    "Accept" = "application/vnd.github.v3+json"
}

$releaseData = @{
    tag_name = $tag
    name = $releaseName
    body = $body
    draft = $false
    prerelease = $false
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "https://api.github.com/repos/$owner/$repo/releases" `
        -Method Post `
        -Headers $headers `
        -Body $releaseData `
        -ContentType "application/json"
    
    Write-Host "Release created successfully!" -ForegroundColor Green
    Write-Host "Release ID:" $response.id -ForegroundColor Gray
    Write-Host "URL:" $response.html_url -ForegroundColor Gray
    
    # Upload the installer
    Write-Host ""
    Write-Host "Uploading installer (this may take a few minutes)..." -ForegroundColor Cyan
    
    $uploadUrl = $response.upload_url -replace '\{\?name,label\}', "?name=VortexSetup.exe"
    
    $uploadHeaders = @{
        "Authorization" = "token $Token"
        "Content-Type" = "application/octet-stream"
    }
    
    $fileBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $installerPath))
    
    $uploadResponse = Invoke-RestMethod -Uri $uploadUrl `
        -Method Post `
        -Headers $uploadHeaders `
        -Body $fileBytes
    
    Write-Host "Installer uploaded successfully!" -ForegroundColor Green
    Write-Host "Download URL:" $uploadResponse.browser_download_url -ForegroundColor Gray
    
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host "  Release Published Successfully!" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "View release:" $response.html_url -ForegroundColor Cyan
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "ERROR: Failed to create release" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    
    if ($_.ErrorDetails.Message) {
        $errorDetails = $_.ErrorDetails.Message | ConvertFrom-Json
        $detailMsg = $errorDetails.message
        Write-Host "Details: $detailMsg" -ForegroundColor Red
    }
    
    exit 1
}
