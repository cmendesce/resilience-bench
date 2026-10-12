import threading
import time
from logger import get_logger

logger = get_logger('timeline')

def validate_windows(windows):
    """
    Checks that fault windows are a non-empty list of {start, duration} (ms) sorted by start and not overlapping.
    """
    if not isinstance(windows, list) or not windows:
        raise ValueError('fault.windows must be a non-empty list')
    previous_end = 0
    for idx, window in enumerate(windows):
        if not isinstance(window, dict) or 'start' not in window or 'duration' not in window:
            raise ValueError(f'fault.windows[{idx}] must have start and duration')
        start, duration = window['start'], window['duration']
        if not isinstance(start, (int, float)) or start < 0:
            raise ValueError(f'fault.windows[{idx}].start must be >= 0')
        if not isinstance(duration, (int, float)) or duration <= 0:
            raise ValueError(f'fault.windows[{idx}].duration must be > 0')
        if start < previous_end:
            raise ValueError(f'fault.windows[{idx}] starts before the previous window ends')
        previous_end = start + duration

class FaultTimeline:
    """
    Turns the fault on during each window and off outside them, with windows relative to start().
    """

    def __init__(self, envoy, fault_spec, percentage, windows):
        self._envoy = envoy
        self._fault_spec = fault_spec
        self._percentage = percentage
        self._windows = windows
        self._stop_event = threading.Event()
        self._thread = None
        self._start_time = None
        self.windows_started = 0
        self.windows_completed = 0
        self.duration_ms = None

    def start(self):
        self._set_fault(0)
        self._start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self.duration_ms = round((time.monotonic() - self._start_time) * 1000)
        self._stop_event.set()
        self._thread.join()
        self._set_fault(0)
        if self.windows_completed < len(self._windows):
            logger.warning(f'scenario ended after {self.duration_ms} ms, before fault windows finished: '
                           f'{self.windows_completed}/{len(self._windows)} completed, {self.windows_started} started')

    def _run(self):
        for idx, window in enumerate(self._windows):
            if self._wait_until(window['start']):
                return
            self._set_fault(self._percentage)
            self.windows_started = idx + 1
            logger.info(f'fault window {idx + 1}/{len(self._windows)} on at {self._elapsed_ms()} ms')
            if self._wait_until(window['start'] + window['duration']):
                return
            self._set_fault(0)
            self.windows_completed = idx + 1
            logger.info(f'fault window {idx + 1}/{len(self._windows)} off at {self._elapsed_ms()} ms')

    def _wait_until(self, offset_ms):
        """Waits until offset_ms after start; returns True if stopped first."""
        remaining = self._start_time + offset_ms / 1000 - time.monotonic()
        return self._stop_event.wait(max(remaining, 0))

    def _elapsed_ms(self):
        return round((time.monotonic() - self._start_time) * 1000)

    def _set_fault(self, percentage):
        try:
            self._envoy.set_fault(self._fault_spec, percentage)
        except Exception as e:
            logger.error(f'Failed to set fault to {percentage}% in envoy! {e}')
