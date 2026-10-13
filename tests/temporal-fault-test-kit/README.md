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

1. Check out the feature branch and build/start the Docker Compose environment using the repository's normal setup instructions.
2. In `docker-compose.yaml`, temporarily change the scheduler's config volume to the test file, for example:

   ```yaml
   volumes:
     - ./tests/temporal-fault-test-kit/configs/01-abort-single-window.json:/opt/app/conf/conf.json
     - ./results:/opt/app/resilience-tests
   ```

   Keep the remaining scheduler volumes and environment variables intact.
3. Run one file at a time:

   ```sh
   docker-compose up --build --abort-on-container-exit
   ```

   Use `docker compose` instead if that is the installed CLI.
4. Inspect scheduler logs, Envoy access logs and generated CSVs. Then run `docker-compose down` before the next config. Each file has a unique `testId`.
5. For each file in `invalid-configs/`, mount it and check for a clear startup validation error and no client scenario execution.

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
