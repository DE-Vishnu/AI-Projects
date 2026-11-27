---
runbook_id: RB-SPARK-04
title: "Spark workload memory and shuffle troubleshooting"
service: customer_360_pipeline
triggers:
  - "oom"
  - "memory_pressure"
  - "shuffle_spill"
  - "partition_change"
---

# Spark workload memory and shuffle troubleshooting

## When to use

Use this runbook for service `customer_360_pipeline` when one or more of these conditions apply:

- oom
- memory_pressure
- shuffle_spill
- partition_change

## Pre-deployment and diagnostic checks

- Inspect skew and shuffle partition sizes
- Compare executor memory and spill to baseline
- Run representative-volume performance tests

## Rollback steps

1. Restore previous partition configuration
2. Revert risky join or repartition changes
3. Rerun the failed bounded workload

## Rollback triggers

- Executor OOM repeats
- Spill or runtime exceeds agreed baseline

## Operational note

Follow the service owner’s approved change procedure. Record evidence, timestamps and the release identifier when executing these steps.
