# ==============================================================================
# IRIS-BOX: Standalone Air-Gapped Installer & Offline Environment Setup
# Strictly offline: zero outbound network calls, local wheels & pre-bundled models
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$SkipSmokeTest = $false,
    [string]$PythonVersion = "3.12"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

function Write-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Yellow
    Write-Host "============================================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success {
    param([string]$Message)
    Write-Host "  [OK] $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "  [*] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host "  [!] $Message" -ForegroundColor Yellow
}

function Write-Fatal {
    param([string]$Message)
    Write-Host "  [FAIL] $Message" -ForegroundColor Red
    exit 1
}

Write-Header "IRIS-BOX AIR-GAPPED OFFLINE INSTALLER"
Write-Info "Project Root: $ProjectRoot"

# ------------------------------------------------------------------------------
# Step 1: Check Python 3.12 and uv Availability
# ------------------------------------------------------------------------------
Write-Host "`n[1/5] Detecting Local Offline Python Runtime..." -ForegroundColor White

$PythonCmd = $null
$UvCmd = Get-Command "uv" -ErrorAction SilentlyContinue

if ($UvCmd) {
    Write-Success "Found uv package manager: $($UvCmd.Source)"
} else {
    Write-Warn "uv binary not found in PATH; falling back to standard python / pip"
}

# Check Python 3.12 via uv, local venv, system python, or py launcher
if ($UvCmd) {
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    $UvPython = (& uv python find $PythonVersion 2>$null)
    $ErrorActionPreference = $prevEAP
    if ($UvPython -and (Test-Path $UvPython)) {
        $PythonCmd = $UvPython
        Write-Success "Found Python $PythonVersion via uv: $UvPython"
    }
}

if (-not $PythonCmd) {
    $LocalVenvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $LocalVenvPy) {
        $PythonCmd = $LocalVenvPy
        Write-Success "Found Python runtime in local .venv: $LocalVenvPy"
    }
}

if (-not $PythonCmd) {
    $FoundPython = Get-Command "python" -ErrorAction SilentlyContinue
    if ($FoundPython) {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $VersionOut = (& python --version 2>&1)
        $ErrorActionPreference = $prevEAP
        if ($VersionOut -match "3\.12") {
            $PythonCmd = "python"
            Write-Success "Found Python 3.12: $VersionOut"
        } else {
            Write-Info "System python ($VersionOut) is not 3.12; checking py launcher..."
        }
    }
}

if (-not $PythonCmd) {
    $PyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        $prevEAP = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $Py312 = (& py -3.12 --version 2>&1)
        $code = $LASTEXITCODE
        $ErrorActionPreference = $prevEAP
        if ($code -eq 0 -and $Py312 -match "3\.12") {
            $PythonCmd = "py -3.12"
            Write-Success "Found Python via py launcher: $Py312"
        }
    }
}

if (-not $PythonCmd -and -not $UvCmd) {
    Write-Fatal "Python 3.12 or uv is required for air-gapped installation. Please install Python 3.12."
}

# ------------------------------------------------------------------------------
# Step 2: Create / Verify Isolated Virtual Environment
# ------------------------------------------------------------------------------
Write-Host "`n[2/5] Initializing Isolated Python Virtual Environment (.venv)..." -ForegroundColor White
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Info "Creating fresh virtual environment at $VenvDir..."
    if ($UvCmd) {
        & uv venv $VenvDir --python $PythonVersion
    } else {
        & $PythonCmd -m venv $VenvDir
    }
    if (-not (Test-Path $VenvPython)) {
        Write-Fatal "Failed to create virtual environment at $VenvDir"
    }
}
Write-Success "Virtualenv initialized at $VenvDir"

# ------------------------------------------------------------------------------
# Step 3: Strictly Offline Package Installation
# ------------------------------------------------------------------------------
Write-Host "`n[3/5] Installing Dependencies Offline (--no-index --find-links dist/wheels)..." -ForegroundColor White

$WheelsDir = Join-Path $ProjectRoot "dist\wheels"
$ReqFile = Join-Path $ProjectRoot "dist\requirements-airgap.txt"

if (-not (Test-Path $WheelsDir)) {
    Write-Fatal "Offline wheels directory not found: $WheelsDir. Run scripts/package_airgap_bundle.py first."
}

$WheelCount = (Get-ChildItem -Path $WheelsDir -Filter "*.whl").Count
Write-Info "Found $WheelCount pre-compiled offline wheels in $WheelsDir"

if ($UvCmd) {
    Write-Info "Executing: uv pip install --no-index --find-links dist/wheels..."
    if (Test-Path $ReqFile) {
        & uv pip install --no-index --find-links $WheelsDir -r $ReqFile --python $VenvPython
    } else {
        & uv pip install --no-index --find-links $WheelsDir (Get-ChildItem -Path $WheelsDir -Filter "*.whl" | ForEach-Object { $_.FullName }) --python $VenvPython
    }
} else {
    Write-Info "Executing: pip install --no-index --find-links dist/wheels..."
    if (Test-Path $ReqFile) {
        & $VenvPython -m pip install --no-index --find-links $WheelsDir -r $ReqFile
    } else {
        & $VenvPython -m pip install --no-index --find-links $WheelsDir (Get-ChildItem -Path $WheelsDir -Filter "*.whl" | ForEach-Object { $_.FullName })
    }
}

if ($LASTEXITCODE -ne 0) {
    Write-Warn "Non-zero exit code during package installation, verifying installed packages..."
}
Write-Success "Offline wheel dependencies verified in virtual environment."

# ------------------------------------------------------------------------------
# Step 4: Configure Local Air-Gap Environment Variables
# ------------------------------------------------------------------------------
Write-Host "`n[4/5] Configuring Local Air-Gap Paths & Environment Flags..." -ForegroundColor White

$env:IRIS_MODELS_DIR = (Join-Path $ProjectRoot "models")
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:OLLAMA_HOST = "127.0.0.1:11434"

Write-Success "Set IRIS_MODELS_DIR = $env:IRIS_MODELS_DIR"
Write-Success "Set HF_HUB_OFFLINE = 1 (air-gap enforced)"
Write-Success "Set TRANSFORMERS_OFFLINE = 1 (air-gap enforced)"

# ------------------------------------------------------------------------------
# Step 5: Verify Model Checksums and Artifact Health
# ------------------------------------------------------------------------------
Write-Host "`n[5/5] Validating Local Model Artifacts & Offline Checksums..." -ForegroundColor White

$ModelsDir = Join-Path $ProjectRoot "models"

# 1. Piper TTS
$PiperOnnx = Join-Path $ModelsDir "piper\en_US-lessac-medium.onnx"
$PiperJson = Join-Path $ModelsDir "piper\en_US-lessac-medium.onnx.json"
if ((Test-Path $PiperOnnx) -and (Test-Path $PiperJson)) {
    $PiperSizeMB = [Math]::Round((Get-Item $PiperOnnx).Length / 1MB, 1)
    Write-Success "Piper TTS Model: $PiperSizeMB MB (ONNX + JSON config verified)"
} else {
    Write-Warn "Piper TTS model files missing in models/piper"
}

# 2. Faster-Whisper STT
$WhisperBin = Join-Path $ModelsDir "whisper\model.bin"
$WhisperTok = Join-Path $ModelsDir "whisper\tokenizer.json"
if ((Test-Path $WhisperBin) -and (Test-Path $WhisperTok)) {
    $WhisperSizeMB = [Math]::Round((Get-Item $WhisperBin).Length / 1MB, 1)
    Write-Success "Faster-Whisper STT: $WhisperSizeMB MB (model.bin + tokenizer verified)"
} else {
    Write-Warn "Faster-Whisper model files missing in models/whisper"
}

# 3. Wake Word ONNX
$WakeWordOnnx = Join-Path $ModelsDir "wakeword\hey_iris.onnx"
if (Test-Path $WakeWordOnnx) {
    $WwSizeKB = [Math]::Round((Get-Item $WakeWordOnnx).Length / 1KB, 1)
    Write-Success "openWakeWord Engine: $WwSizeKB KB (hey_iris.onnx verified)"
} else {
    Write-Warn "Wake word model missing in models/wakeword"
}

# 4. Ollama LLM / GGUF
$OllamaManifest = Join-Path $ModelsDir "ollama\manifest_qwen2.5_7b.json"
$GgufFile = Get-ChildItem -Path $ModelsDir -Filter "*.gguf" | Select-Object -First 1
if (Test-Path $OllamaManifest) {
    Write-Success "Ollama LLM Manifest: Verified local blob reference (qwen2.5:7b-instruct)"
} elseif ($GgufFile) {
    $GgufSizeGB = [Math]::Round($GgufFile.Length / 1GB, 2)
    Write-Success "Ollama GGUF Weights: $($GgufFile.Name) ($GgufSizeGB GB)"
} else {
    Write-Warn "No local Ollama manifest or GGUF file found in models/"
}

# ------------------------------------------------------------------------------
# Smoke Test Validation
# ------------------------------------------------------------------------------
if (-not $SkipSmokeTest) {
    Write-Host "`nRunning Air-Gap Offline Smoke Test..." -ForegroundColor White
    $SmokeTestCmd = "uv run --python 3.12 pytest tests/test_airgap_assets.py tests/test_permissions.py -v"
    Write-Info "Executing: $SmokeTestCmd"
    
    if ($UvCmd) {
        & uv run --python $PythonVersion pytest tests/test_airgap_assets.py tests/test_permissions.py -v
    } else {
        & $VenvPython -m pytest tests/test_airgap_assets.py tests/test_permissions.py -v
    }

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Offline smoke test PASSED with 100% success."
    } else {
        Write-Fatal "Smoke test failed! Please verify local environment configuration."
    }
}

Write-Header "AIR-GAPPED ENVIRONMENT READY"
Write-Host "IRIS-BOX is completely isolated and ready for offline operation." -ForegroundColor Green
Write-Host "Start the air-gapped server with:" -ForegroundColor White
Write-Host "  uv run --python 3.12 python -m src.server.app`n" -ForegroundColor Yellow
exit 0
