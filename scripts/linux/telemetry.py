"""Lightweight, read-only system measurements for local validation reports."""
from pathlib import Path
import threading
import time
import subprocess
from localai import memory, running, process_identity, profiles

_container_pid = None

def runtime_pid(owner):
    """Resolve this controller's container once; conmon reparents outside podman's tree."""
    global _container_pid
    if profiles()[owner['profile']]['engine'] != 'gufo': return owner['pid']
    key = (owner['pid'], owner['identity'])
    if _container_pid and _container_pid[0] == key and process_identity(_container_pid[1]) == _container_pid[2]:
        return _container_pid[1]
    try:
        result = subprocess.run(['podman', 'inspect', '--format', '{{.State.Pid}}', 'localai-gufo'],
                                capture_output=True, text=True, timeout=3, check=True)
        pid = int(result.stdout.strip())
        identity = process_identity(pid)
        if pid > 1 and identity:
            _container_pid = (key, pid, identity)
            return pid
    except (OSError, ValueError, subprocess.SubprocessError): pass
    return None

def sample():
    result = {'time': time.time(), **memory(), 'temperatures_c': {}, 'power_w': {}}
    result['gpu_clock_state'] = {}
    for device in Path('/sys/class/drm').glob('card*/device'):
        for name in ('power_dpm_force_performance_level', 'pp_dpm_sclk', 'pp_dpm_fclk', 'gpu_busy_percent'):
            try: result['gpu_clock_state'][name] = (device / name).read_text().strip()
            except OSError: pass
    try: result['platform_profile'] = Path('/sys/firmware/acpi/platform_profile').read_text().strip()
    except OSError: pass
    result['ac_online'] = any(p.read_text().strip() == '1' for p in Path('/sys/class/power_supply').glob('AC*/online'))
    try:
        vm = dict(line.split() for line in Path('/proc/vmstat').read_text().splitlines())
        result['swap_in_pages'] = int(vm['pswpin'])
        result['swap_out_pages'] = int(vm['pswpout'])
    except (OSError, ValueError, KeyError): pass
    owner = running()
    if owner:
        try:
            status = dict(line.split(':', 1) for line in Path(f'/proc/{owner["pid"]}/status').read_text().splitlines() if ':' in line)
            result['owned_process'] = {'pid': owner['pid'], 'profile': owner['profile'],
                **{key: int(status[key].split()[0]) * 1024 for key in ('VmRSS', 'VmSwap') if key in status}}
        except (OSError, ValueError, KeyError): pass
        pid = runtime_pid(owner)
        if pid:
            try:
                status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
                result['runtime_process'] = {'pid': pid, 'profile': owner['profile'],
                    **{key: int(status[key].split()[0]) * 1024 for key in ('VmRSS', 'VmSwap') if key in status}}
            except (OSError, ValueError, KeyError): pass
    for sensor in Path('/sys/class/hwmon').glob('hwmon*'):
        try: name = (sensor / 'name').read_text().strip()
        except OSError: continue
        if name not in ('amdgpu', 'k10temp', 'zenpower', 'asus'): continue
        for pattern, field, divisor in (('temp*_input', 'temperatures_c', 1000), ('power*_average', 'power_w', 1000000)):
            for path in sensor.glob(pattern):
                try:
                    label_file = path.with_name(path.name.rsplit('_', 1)[0] + '_label')
                    label = label_file.read_text().strip() if label_file.exists() else path.stem
                    result[field][name + '/' + label] = int(path.read_text()) / divisor
                except (OSError, ValueError): continue
    return result

class Monitor:
    def __init__(self):
        self.samples = []
        self.finished = threading.Event()

    def collect(self):
        while not self.finished.is_set():
            try: self.samples.append(sample())
            except (OSError, ValueError): pass
            self.finished.wait(2)

    def __enter__(self):
        self.thread = threading.Thread(target=self.collect, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.finished.set()
        self.thread.join(timeout=3)

    def report(self):
        return {'samples': self.samples,
                'minimum_available_bytes': min((s['unified_available_bytes'] for s in self.samples), default=None),
                'swap_in_pages_delta': self.samples[-1].get('swap_in_pages', 0) - self.samples[0].get('swap_in_pages', 0) if self.samples else None,
                'swap_out_pages_delta': self.samples[-1].get('swap_out_pages', 0) - self.samples[0].get('swap_out_pages', 0) if self.samples else None,
                'limitations': 'Two-second samples may miss short peaks. Swap counters are system-wide and may include other apps. owned_process may be a container launcher; runtime_process resolves the owned Gufo container host PID when available. Both exclude descendants and some GPU mappings. Power fields cover only available sensors; they are not whole-device wall power.'}
