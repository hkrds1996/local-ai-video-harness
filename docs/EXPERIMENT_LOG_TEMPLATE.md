# Experiment Log Template

Create one copy for every measured run. Keep raw logs private if they contain machine paths, usernames, network addresses, or model locations. Publish only sanitized measurements.

## Run identity

- Date and time:
- Git commit:
- Project manifest:
- Model name and version:
- Model precision or quantization:
- Workflow checksum:
- Harness version:
- GPU:
- VRAM:
- CPU and system memory:
- Operating system:
- Driver version:

## Input and output

- Number of planned shots:
- Planned duration:
- Final duration:
- Resolution and frame rate:
- Successful shots:
- Failed shots:
- Retries:
- Total generated frames:
- Final output size:
- Human review time:
- Publishable on first pass: yes/no

## Runtime measurements

| Stage | Wall time | GPU time | Peak VRAM | Notes |
|---|---:|---:|---:|---|
| Model startup |  |  |  |  |
| Video generation |  |  |  |  |
| Narration |  |  |  |  |
| Caption rendering |  |  |  |  |
| Final composition |  |  |  |  |
| Total |  |  |  |  |

## Cost inputs

| Cost category | Unit | Quantity | Unit cost | Run cost | Notes |
|---|---|---:|---:|---:|---|
| GPU depreciation or rental | USD/hour |  |  |  |  |
| Electricity | kWh |  |  |  |  |
| Storage | GB-month |  |  |  |  |
| Narration | USD/run |  |  |  | local or external |
| Software or API fees | USD/run |  |  |  |  |
| Engineering time | hours |  |  |  | report separately |
| Human review | minutes |  |  |  | report separately |

## Quality measurements

- Output completion rate:
- Retry rate:
- Continuity failures:
- Visual artifact count:
- Generated text artifacts:
- Narration errors:
- Caption timing errors:
- Manual edits required:

## Claim discipline

Do not call a run "fully local" unless every generation, narration, transcription, and composition component runs locally. If any stage uses an online service, call the pipeline hybrid and identify that dependency. Do not call the pipeline "free" without reporting hardware, electricity, storage, setup, and review costs.
