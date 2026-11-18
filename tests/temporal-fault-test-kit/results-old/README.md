# Smoke-test results

Results of running every config in this kit on 2026-11-03, one folder per config file, with relative window starts and `repeat` (#6).

## How they were produced

- Branch `test/temporal-fault-runtime-plan` with `feat/relative-fault-windows` merged in (which includes the access-log storage from #3 and the server health check from #5), run locally with Docker Compose (Colima, aarch64) and this kit's `docker-compose.yaml` override.
- Each config ran on a fresh stack (`down -v` between configs).
- [`../check_results.py`](../check_results.py) checked every folder against its config, and all 12 passed. See [Checks](#checks).

## Files in each folder

| File | Content |
|---|---|
| `exit_code` | Scheduler exit code (0 for valid configs, 1 for the invalid ones) |
| `results.csv`, `results_<group>.csv` | Scheduler results; not written for invalid configs |
| `scenarios.json`, `scenarios-original.json` | Scenarios built from the config, and the config itself |
| `scheduler.log` | Scheduler log, including the fault window on/off times |
| `accesslog_<group>.log.gz` | Envoy access log saved by the scheduler for each group |
| `server.log.gz` | Server container output (supervisord, Envoy and httpbin), without the access-log lines, which are in `accesslog_<group>.log.gz` |
| `compose.log` | Combined `docker compose up` output |

## Checks

For each folder, `check_results.py` checks:

- The exit code. For invalid configs, it also checks the validation error and that no scenario ran.
- The number of result rows.
- Every window on/off time in `scheduler.log` against the configured schedule, which must be met within 50 ms. Starts are relative to the end of the previous window, and the list cycles with `repeat`.
- That the window counts in `results.csv` match the log.
- Every request in the access logs against the windows as they actually turned on and off:
  - No faulted request outside a window.
  - At 100% abort, no successful request inside a window.
  - Requests within 5 ms of a window edge may land on either side and are counted separately.

## Summary

| Config | Outcome |
|---|---|
| `01-abort-single-window` | 1/1 window in all 6 scenarios, at most 16 ms late. Failed requests: baseline Polly 8,320 and Resilience4j 9,907; retry 25 and 50; circuit breaker 44 and 55. 18,400 503s inside the window, none outside; 9 requests within 5 ms of an edge |
| `02-abort-repeated-windows-reset` | 2/2 windows in every scenario and both rounds, on at about 500 and 2,500 ms (second `start` is 1,000 ms after the first window ends), at most 16 ms late; the clock resets each scenario. No 503s outside the windows and no 200s inside; 16 requests within 5 ms of an edge |
| `03-abort-percentage-expansion` | Groups `f50u5` and `f100u5`. At 50%, 50.9% of the requests inside the window failed (1,088 and 472 failed requests); at 100%, all of them (12,001 and 26,686). No 503s outside the window |
| `04-delay-window-boundary` | 10 delayed requests (1,501–1,509 ms), one per user per scenario, all started inside the window (2 within 5 ms of its end); none after it |
| `05-bernoulli-regression-no-windows` | No time-window columns; 0% 503s at 0% and 50.4% at 50% |
| `06-short-scenario-missed-window` | Warning in both scenarios, 0 windows started and completed |
| `07-abort-repeat` | Up 1,000 ms, down 1,000 ms, repeated: 8 windows in each scenario (17.0 s for Polly, 16.6 s for Resilience4j), all completed, at most 5 ms late with no drift. `faultRepeat` is `True`, no warning. No 503s outside the windows and no 200s inside; 86 requests within 5 ms of an edge |
| `invalid-*` | Exit code 1 with a validation error before any scenario: `start must be >= 0`, `duration must be > 0`, `fault.repeat must be true or false`, `fault.repeat requires fault.windows`, and `fault.repeat needs at least one window with start > 0` |
