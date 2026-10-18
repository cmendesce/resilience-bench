# ResilienceBench temporal-fault smoke-test kit

This is a small **runtime verification plan** for the `feat/time-window-faults` implementation. It is not the journal experiment matrix and its example timings are illustrative only. Run one configuration at a time in a disposable/local environment because scenarios change shared Envoy runtime settings.

## Contents

| File | Purpose | Main pass criteria |
|---|---|---|
| `configs/01-abort-single-window.json` | One 100% 503 window; baseline, Retry, Circuit Breaker in Polly and Resilience4j | Window transitions occur, requests fail inside and succeed outside, all six scenarios cover the window |
| `configs/02-abort-repeated-windows-reset.json` | Two abort windows, two rounds | Both windows are observed per round; each scenario resets the clock; no fault leaks |
| `configs/03-abort-percentage-expansion.json` | 50% and 100% inside one window | Scenario groups are `f50u5` and `f100u5`; partial and full faulting differ as expected |
| `configs/04-delay-window-boundary.json` | Delay active for a short window, with a longer injected delay | A request selected inside the window remains delayed even if the window ends; later requests are not delayed |
| `configs/05-bernoulli-regression-no-windows.json` | Existing Bernoulli mode, no `windows` key | Old mode remains unchanged; temporal-only result fields are absent |
| `configs/06-short-scenario-missed-window.json` | Workload completes before the first window | Warning and 0/0 started/completed counts; treat this as an intentionally incomplete diagnostic run |
| `invalid-configs/*.json` | Negative start, zero duration, overlap, unsorted windows | Startup validation fails before executing scenarios |

Cockatiel is omitted because the feature PR description notes a separate, pre-existing client issue.

## How to run

The kit ships a Compose override, [`docker-compose.yaml`](./docker-compose.yaml), that runs everything locally: it mounts the selected test config into the scheduler and stores results on the local file system (`DISK_PATH`), so no AWS credentials or S3 bucket are needed and the repository's `docker-compose.yaml` stays untouched.

1. From the repository root, pick a config with `TEST_CONFIG` (a path relative to this folder) and run it:

   ```sh
   TEST_CONFIG=configs/01-abort-single-window.json \
     docker compose -f docker-compose.yaml -f tests/temporal-fault-test-kit/docker-compose.yaml \
     up --build --abort-on-container-exit --exit-code-from scheduler scheduler
   ```

   Naming the `scheduler` service starts only it and its dependencies (server, Polly, Resilience4j), so the Cockatiel client is not built. Use `docker-compose` instead of `docker compose` if that is the installed CLI.
2. Results are written to `tests/temporal-fault-test-kit/results/<testId>/` (ignored by git). Inspect them together with the scheduler logs and Envoy access logs.
3. Tear the environment down before the next config, so Envoy starts with a clean runtime:

   ```sh
   docker compose -f docker-compose.yaml -f tests/temporal-fault-test-kit/docker-compose.yaml down
   ```

   Each file has a unique `testId`, so results from different configs do not overwrite each other.
4. For each file in `invalid-configs/`, run it the same way (e.g. `TEST_CONFIG=invalid-configs/invalid-overlap.json`) and check for a clear startup validation error and no client scenario execution; the scheduler exits with a non-zero code.

## Pass/fail checklist

### Abort windows and repeated windows
- `faultWindows` matches the configured schedule.
- `faultWindowsStarted` and `faultWindowsCompleted` equal the configured window count; `scenarioDurationMs` covers the final window.
- Logs show transitions close to the intended times. Record scheduled-versus-actual transition timing if available.
- Envoy access logs show injected 503/`FI` responses during windows and successful forwarding outside them. Inspect requests near boundaries separately.
- A sanity request after the scenario succeeds, demonstrating cleanup.
- For repeated windows, verify every window in every round rather than relying on aggregate counts.

### Percentage expansion
- Both expected groups (`f50u5` and `f100u5`) are present.
- For 50%, some but not necessarily exactly half of requests inside the window fail; for 100%, all eligible requests should fail except boundary races.
- Outside windows, injected aborts should be zero.

### Delay boundary
- A request selected for delay inside the window keeps the assigned delay even when its completion falls after deactivation.
- Requests arriving after deactivation do not incur the injected delay.
- Delay is disabled after scenario completion.

### Bernoulli regression and missed-window diagnostic
- Without `windows`, behavior matches the prior per-request fault mode and temporal-only columns are absent.
- The short scenario warns and reports zero windows started/completed. This is not a valid experimental observation.

### Invalid input
- Each invalid file fails fast with a clear startup/validation error; no client scenarios begin.

## Publication-data safeguard

The current feature PR catches/logs exceptions from the Envoy transition call. Before collecting data for a paper, transition errors should make the run visibly invalid instead of being counted as successful transitions, while cleanup still attempts to disable fault injection. Keep the raw scheduler and Envoy logs for these smoke tests.
