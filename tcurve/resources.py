import shutil
import subprocess
import time


class ResourceMonitor(object):
    def __init__(self, interval=1.0, retry_interval=10.0):
        self.interval = interval
        self.retry_interval = retry_interval
        self.last_sample_time = 0.0
        self.last_gpu_attempt_time = 0.0
        self.snapshot_cache = None
        self.gpu_available = None
        self.gpu_error = ''
        self.prev_cpu_total = None
        self.prev_cpu_idle = None

    def snapshot(self):
        now = time.time()
        if self.snapshot_cache is not None and now - self.last_sample_time < self.interval:
            return self.snapshot_cache
        self.snapshot_cache = {
            'cpu': self._cpu_percent(),
            'memory': self._memory_percent(),
            'gpus': self._gpu_stats(now),
            'gpu_error': self.gpu_error,
        }
        self.last_sample_time = now
        return self.snapshot_cache

    def _cpu_percent(self):
        try:
            import psutil
        except ImportError:
            return self._cpu_percent_proc()
        return psutil.cpu_percent(interval=None)

    def _memory_percent(self):
        try:
            import psutil
        except ImportError:
            return self._memory_percent_proc()
        mem = psutil.virtual_memory()
        return {
            'percent': mem.percent,
            'used_gb': mem.used / (1024 ** 3),
            'total_gb': mem.total / (1024 ** 3),
        }

    def _cpu_percent_proc(self):
        try:
            with open('/proc/stat', 'r') as f:
                fields = f.readline().split()
        except OSError:
            return None
        if not fields or fields[0] != 'cpu':
            return None
        try:
            values = [float(value) for value in fields[1:]]
        except ValueError:
            return None
        if len(values) < 4:
            return None
        idle = values[3] + (values[4] if len(values) > 4 else 0.0)
        total = sum(values)
        if self.prev_cpu_total is None or self.prev_cpu_idle is None:
            self.prev_cpu_total = total
            self.prev_cpu_idle = idle
            return 0.0
        total_delta = total - self.prev_cpu_total
        idle_delta = idle - self.prev_cpu_idle
        self.prev_cpu_total = total
        self.prev_cpu_idle = idle
        if total_delta <= 0:
            return 0.0
        return max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0))

    def _memory_percent_proc(self):
        values = {}
        try:
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        values[parts[0].rstrip(':')] = float(parts[1])
        except OSError:
            return None
        total = values.get('MemTotal')
        available = values.get('MemAvailable')
        if total is None or available is None or total <= 0:
            return None
        used = total - available
        return {
            'percent': used / total * 100.0,
            'used_gb': used * 1024.0 / (1024 ** 3),
            'total_gb': total * 1024.0 / (1024 ** 3),
        }

    def _set_gpu_unavailable(self, now, message):
        self.gpu_available = False
        self.last_gpu_attempt_time = now
        self.gpu_error = message
        return []

    def _gpu_stats(self, now):
        if self.gpu_available is False and now - self.last_gpu_attempt_time < self.retry_interval:
            return []
        if shutil.which('nvidia-smi') is None:
            return self._set_gpu_unavailable(now, 'nvidia-smi not found')
        self.last_gpu_attempt_time = now
        try:
            result = subprocess.run(
                [
                    'nvidia-smi',
                    '--query-gpu=index,utilization.gpu,temperature.gpu,memory.used,memory.total',
                    '--format=csv,noheader,nounits',
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=0.2,
            )
        except subprocess.TimeoutExpired:
            return self._set_gpu_unavailable(now, 'nvidia-smi timed out')
        except (OSError, subprocess.SubprocessError) as exc:
            return self._set_gpu_unavailable(now, str(exc))
        if result.returncode != 0:
            message = (result.stderr or result.stdout or 'nvidia-smi failed').strip().splitlines()[0]
            return self._set_gpu_unavailable(now, message)
        gpus = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(',')]
            if len(parts) != 5:
                continue
            try:
                gpus.append({
                    'index': int(parts[0]),
                    'util': float(parts[1]),
                    'temperature_c': float(parts[2]),
                    'memory_used_mb': float(parts[3]),
                    'memory_total_mb': float(parts[4]),
                })
            except ValueError:
                continue
        self.gpu_available = True
        self.gpu_error = ''
        return gpus
