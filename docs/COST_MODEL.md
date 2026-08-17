# Cost Model

## Purpose

The experiment asks how close a local pipeline is to zero marginal API cost. It does not assume local inference is free.

## Cost boundaries

Report at least three views:

1. Cash cost per run: electricity, paid APIs, rented compute, and incremental storage.
2. Amortized infrastructure cost: GPU, workstation, and storage depreciation allocated across useful runs.
3. Full production cost: cash and infrastructure cost plus engineering and human review time.

Do not combine these into a single number without also publishing the components.

## Suggested formulas

```text
electricity_cost = average_system_kw * runtime_hours * electricity_rate_per_kwh

gpu_cost_per_hour = gpu_purchase_price / expected_useful_gpu_hours

amortized_gpu_cost = gpu_cost_per_hour * gpu_runtime_hours

storage_cost = output_gb * monthly_storage_rate_per_gb * retention_months

cash_cost_per_success = total_cash_cost / successful_publishable_outputs

full_cost_per_success = (
    total_cash_cost
    + amortized_infrastructure_cost
    + engineering_hours * engineering_hour_value
    + review_hours * review_hour_value
) / successful_publishable_outputs
```

## Measurements that matter

- startup time before the first generation;
- generation time per output second;
- number of failed or discarded generations;
- retries per accepted shot;
- peak VRAM and system power;
- output storage before and after cleanup;
- human review and editing time;
- percentage of output that is publishable without manual correction.

## Comparison rules

When comparing local and hosted systems, use equivalent resolution, duration, quality target, and retry policy. A local first attempt should not be compared with a hosted final accepted output. Include failed attempts in both cost calculations.

## Interpretation

A zero API invoice can coexist with a high total cost. The useful claim is usually narrower: local inference can reduce marginal vendor charges and increase control when hardware is already available and utilization is high enough.
