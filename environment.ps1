$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$env:HF_HOME = "$root\models\huggingface"
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HF_HUB_DISABLE_XET = '1'
$env:UV_CACHE_DIR = "$root\cache\uv"
$env:UV_PYTHON_INSTALL_DIR = "$root\runtime"
$env:TORCH_HOME = "$root\cache\torch"
$env:XDG_CACHE_HOME = "$root\cache"
$env:NUMBA_CACHE_DIR = "$root\cache\numba"
$env:TEMP = "$root\tmp"
$env:TMP = "$root\tmp"
$env:PYTHONUTF8 = '1'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUNBUFFERED = '1'
$env:CUDA_CACHE_PATH = "$root\cache\cuda"
New-Item -ItemType Directory -Force $env:HF_HOME,$env:TORCH_HOME,$env:NUMBA_CACHE_DIR,$env:CUDA_CACHE_PATH,"$root\generated","$root\logs" | Out-Null
