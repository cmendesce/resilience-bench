# Smoke-test results

Results of running every config in this kit on 2026-10-18, one folder per config file.

## How they were produced

- Branch `test/temporal-fault-runtime-plan` at `bc8757e`, run locally with Docker Compose (Colima, aarch64) and this kit's `docker-compose.yaml` override.
- The override also had the server health check from #5, so the scheduler waited for Envoy and httpbin before the first scenario. Without it, the first scenario of each run hits a server that is not ready yet.
- Each config ran on a fresh stack (`down -v` between configs). `01-abort-single-window` was run a second time on its own: in its first run, the first scenario's window turned on at 3,959 ms instead of 500 ms, and the results still counted it as started and completed.

## Files in each folder

| File | Content |
|---|---|
| `exit_code` | Scheduler exit code (0 for valid configs, 1 for the invalid ones) |
| `results.csv`, `results_<group>.csv` | Scheduler results; not written for invalid configs |
| `scenarios.json`, `scenarios-original.json` | Scenarios built from the config, and the config itself |
| `scheduler.log` | Scheduler log, including the fault window on/off times |
| `server.log.gz` | Server container output: Envoy's stdout access log plus supervisord. Its last lines can be missing because the stack stops as soon as the scheduler exits |
| `compose.log` | Combined `docker compose up` output |

## Summary

| Config | Outcome |
|---|---|
| `01-abort-single-window` | 1/1 window in all 6 scenarios, transitions 1–16 ms after schedule. Baseline failures: Polly 9,856, Resilience4j 8,275; retry and circuit breaker 30–55. Wrong-side requests: 13, all within 3 ms of a window edge |
| `02-abort-repeated-windows-reset` | 2/2 windows in every scenario and both rounds; the clock resets each scenario. Wrong-side requests: 29, all within 1 ms of an edge |
| `03-abort-percentage-expansion` | Groups `f50u5` (3,826 and 3,418 failures) and `f100u5` (18,131 and 28,359); no injected 503s outside the window |
| `04-delay-window-boundary` | 10 delayed requests (1,501–1,510 ms), one per user per scenario; none after the window |
| `05-bernoulli-regression-no-windows` | No time-window columns; 0 failures at 0%, about 50% at 50% |
| `06-short-scenario-missed-window` | Warning, 0 windows started and completed |
| `invalid-*` | Exit code 1 with a validation error before any scenario. `invalid-unsorted` reports the overlap message rather than an ordering error |
