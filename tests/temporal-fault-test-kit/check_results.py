"""Checks the temporal-fault test kit's result folders against their configs.

Usage, from the repository root: python3 tests/temporal-fault-test-kit/check_results.py

For each folder in results/ it checks the exit code (and validation error for invalid configs), the number of
result rows, the fault window on/off times in scheduler.log against the configured schedule, the window counts
in results.csv, and every request in the Envoy access logs against the windows as they actually turned on and off.
Prints PASS or FAIL per folder and exits with 1 if any folder failed.
"""
import csv
import datetime as dt
import glob
import gzip
import itertools
import json
import os
import re
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
TRANSITION_TOLERANCE_MS = 50  # actual on/off offset vs schedule
EDGE_S = 0.005                # requests this close to a window edge may land on either side

EXPECTED_ERRORS = {
    'invalid-negative-start': 'fault.windows[0].start must be >= 0',
    'invalid-zero-duration': 'fault.windows[0].duration must be > 0',
    'invalid-repeat-not-boolean': 'fault.repeat must be true or false',
    'invalid-repeat-without-windows': 'fault.repeat requires fault.windows',
    'invalid-repeat-zero-start': 'fault.repeat needs at least one window with start > 0',
}

TRANSITION = re.compile(r'(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+) INFO\s+fault window (\d+) \((\d+)/(\d+) in the list\) (on|off) at (\d+) ms')
ACCESS = re.compile(r'\[(.*?)Z\] "\S+ \S+ \S+" (\d+) (\S+) \d+ \d+ (\d+)')

def schedule(windows, repeat):
    offset = 0
    while True:
        for w in windows:
            on = offset + w['start']
            offset = on + w['duration']
            yield on, offset
        if not repeat:
            return

def parse_transitions(log):
    """Returns one list of (kind, offset_ms, wall_time) per scenario; a scenario restarts at window 1 'on'."""
    scenarios = []
    for line in open(log):
        m = TRANSITION.search(line)
        if not m:
            continue
        wall = dt.datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S,%f')
        n, idx, kind, offset = int(m.group(2)), int(m.group(3)), m.group(5), int(m.group(6))
        if kind == 'on' and n == 1:
            scenarios.append([])
        scenarios[-1].append((kind, offset, wall, idx))
    return scenarios

def check(name, problems, notes):
    folder = os.path.join(KIT, 'results', name)
    cfg_path = os.path.join(KIT, 'invalid-configs' if name.startswith('invalid-') else 'configs', name + '.json')
    cfg = json.load(open(cfg_path))
    exit_code = int(open(os.path.join(folder, 'exit_code')).read())
    log = open(os.path.join(folder, 'scheduler.log')).read()

    if name in EXPECTED_ERRORS:
        if exit_code != 1:
            problems.append(f'exit code {exit_code}, expected 1')
        if EXPECTED_ERRORS[name] not in log:
            problems.append(f'missing error "{EXPECTED_ERRORS[name]}"')
        if 'processing scenario' in log:
            problems.append('a scenario ran')
        notes.append(f'exit 1: {EXPECTED_ERRORS[name]}')
        return

    if exit_code != 0:
        problems.append(f'exit code {exit_code}')
        return
    rows = list(csv.DictReader(open(os.path.join(folder, 'results.csv'))))
    fault = cfg['fault']
    expected_rows = len(cfg['clientSpecs']) * len(fault['percentage']) * sum(cfg['users']) * cfg['rounds']
    if len(rows) != expected_rows:
        problems.append(f'{len(rows)} result rows, expected {expected_rows}')
    if 'Traceback' in log or 'Failed to set fault' in log:
        problems.append('error in scheduler log')

    windows = fault.get('windows')
    if not windows:
        if any('faultWindowsStarted' in r for r in rows):
            problems.append('time-window columns present without windows')
        for pct in fault['percentage']:
            path = glob.glob(os.path.join(folder, f'accesslog_f{pct}u*.log.gz'))[0]
            statuses = [ACCESS.match(l).group(2) for l in gzip.open(path, 'rt') if ACCESS.match(l)]
            ratio = statuses.count('503') / len(statuses)
            notes.append(f'f{pct}: {ratio:.1%} 503s of {len(statuses)} requests')
            if pct == 0 and ratio:
                problems.append(f'f0 has 503s')
            if pct and abs(ratio - pct / 100) > 0.05:
                problems.append(f'f{pct} 503 ratio {ratio:.1%}')
        return

    repeat = fault.get('repeat', False)
    scenarios = parse_transitions(os.path.join(folder, 'scheduler.log'))
    started = sorted({int(r['faultWindowsStarted']) for r in rows})
    expected_scenarios = len(cfg['clientSpecs']) * len(fault['percentage']) * len(cfg['users']) * cfg['rounds']
    if name.startswith('06'):
        if scenarios:
            problems.append('windows started in the short scenario')
        if log.count('before the list of fault windows finished once') != expected_scenarios:
            problems.append('missing missed-window warning')
        if started != [0]:
            problems.append(f'faultWindowsStarted {started}')
        notes.append(f'{expected_scenarios} scenarios, 0 windows, warning logged in each')
        return
    if len(scenarios) != expected_scenarios:
        problems.append(f'{len(scenarios)} scenarios with windows, expected {expected_scenarios}')
    if 'before the list of fault windows finished once' in log:
        problems.append('missed-window warning')

    worst = 0
    counts = []
    for transitions in scenarios:
        expected = [x for on_off in itertools.islice(schedule(windows, repeat), len(transitions)) for x in on_off]
        for (kind, actual, _, _), want in zip(transitions, expected):
            worst = max(worst, actual - want)
            if not 0 <= actual - want <= TRANSITION_TOLERANCE_MS:
                problems.append(f'{kind} at {actual} ms, scheduled {want} ms')
        on = sum(1 for k, *_ in transitions if k == 'on')
        off = sum(1 for k, *_ in transitions if k == 'off')
        counts.append((on, off))
        if not repeat and (on, off) != (len(windows), len(windows)):
            problems.append(f'{on}/{off} windows on/off, expected {len(windows)}')
    csv_counts = sorted({(int(r['faultWindowsStarted']), int(r['faultWindowsCompleted'])) for r in rows})
    if sorted(set(counts)) != csv_counts:
        problems.append(f'log counts {sorted(set(counts))} != results {csv_counts}')
    if repeat and any(r.get('faultRepeat') != 'True' for r in rows):
        problems.append('faultRepeat is not True')
    if repeat:
        for r in rows:
            cycle = sum(w['start'] + w['duration'] for w in windows)
            full = int(r['scenarioDurationMs']) // cycle
            if int(r['faultWindowsCompleted']) < full * len(windows):
                problems.append(f'{r["faultWindowsCompleted"]} windows completed in {r["scenarioDurationMs"]} ms')
    notes.append(f'{len(scenarios)} scenarios, windows on/off per scenario {sorted(set(counts))}, transitions at most {worst} ms late')

    # Access logs: compare each request with the windows as logged (wall clock, UTC)
    spans = []
    for transitions in scenarios:
        on_time = None
        for kind, _, wall, idx in transitions:
            if kind == 'on':
                on_time = (wall, idx)
            else:
                spans.append((on_time[0], wall))
                on_time = None
        if on_time:
            # Still on when the scenario stopped (not logged): the fault was off by the scheduled end at the latest
            spans.append((on_time[0], on_time[0] + dt.timedelta(milliseconds=windows[on_time[1] - 1]['duration'])))

    def inside(t, slack=0.0):
        s = dt.timedelta(seconds=slack)
        return any(a - s <= t <= b + s for a, b in spans)

    for path in sorted(glob.glob(os.path.join(folder, 'accesslog_*.log.gz'))):
        group = re.search(r'accesslog_(.*)\.log\.gz', path).group(1)
        pct = int(re.match(r'f(\d+)u', group).group(1))
        c = dict.fromkeys(['fault_in', 'fault_out', 'fault_edge', 'ok_in', 'ok_edge', 'ok_out'], 0)
        for line in gzip.open(path, 'rt'):
            m = ACCESS.match(line)
            if not m:
                continue
            t = dt.datetime.strptime(m.group(1), '%Y-%m-%dT%H:%M:%S.%f')
            status, flags, duration = m.group(2), m.group(3), int(m.group(4))
            faulted = status == '503' if fault['type'] == 'abort' else duration >= fault['duration']
            if faulted:
                c['fault_in' if inside(t) else 'fault_edge' if inside(t, EDGE_S) else 'fault_out'] += 1
            elif not inside(t):
                c['ok_out'] += 1
            elif inside(t, -EDGE_S):
                c['ok_in'] += 1
            else:
                c['ok_edge'] += 1
        if c['fault_out']:
            problems.append(f'{group}: {c["fault_out"]} faulted requests outside the windows')
        if pct == 100 and fault['type'] == 'abort' and c['ok_in']:
            problems.append(f'{group}: {c["ok_in"]} successful requests inside the windows at 100%')
        if pct < 100 and c['fault_in']:
            ratio = c['fault_in'] / (c['fault_in'] + c['ok_in'])
            notes.append(f'{group}: {ratio:.1%} faulted inside the windows')
        notes.append(f'{group}: {c}')

problems_found = False
for folder in sorted(os.listdir(os.path.join(KIT, 'results'))):
    if not os.path.isdir(os.path.join(KIT, 'results', folder)):
        continue
    problems, notes = [], []
    try:
        check(folder, problems, notes)
    except Exception as e:
        problems.append(f'checker error: {e!r}')
    problems_found |= bool(problems)
    print(f'{"FAIL" if problems else "PASS"} {folder}')
    for n in notes:
        print(f'     {n}')
    for p in problems[:10]:
        print(f'  !! {p}')
sys.exit(1 if problems_found else 0)
