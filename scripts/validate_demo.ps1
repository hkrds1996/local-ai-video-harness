$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $projectRoot 'src'
python -m local_ai_video_harness.cli validate --manifest (Join-Path $projectRoot 'examples\english-rto-demo\project.json')
python -m local_ai_video_harness.cli plan --manifest (Join-Path $projectRoot 'examples\english-rto-demo\project.json')
