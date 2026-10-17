"""Windows desktop resource guard for the existing local Strata servers."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(r'C:\Users\danfl\dev\LocalAI')
STRATA = ROOT / 'apps' / 'Strata'
RUNTIME = ROOT / 'config' / 'strata' / 'runtime'
GIB = 1024 ** 3
MODELS = {
    'iq2xs': ('strata-iq2_xs.json', 8081, 14),
    'qwen36': ('strata-qwen36-ud-q4_k_xl.json', 8080, 14),
}
K = C.WinDLL('kernel32', use_last_error=True)

class Memory(C.Structure):
    _fields_ = [('length', W.DWORD), ('load', W.DWORD)] + [(n, C.c_ulonglong) for n in
        ('total', 'available', 'total_page', 'available_page', 'total_virtual', 'available_virtual', 'extended')]

class BasicLimits(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong), ('flags', W.DWORD),
                ('min_ws', C.c_size_t), ('max_ws', C.c_size_t), ('active', W.DWORD),
                ('affinity', C.c_size_t), ('priority', W.DWORD), ('scheduling', W.DWORD)]

class IOCounters(C.Structure):
    _fields_ = [(n, C.c_ulonglong) for n in ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

class ExtendedLimits(C.Structure):
    _fields_ = [('basic', BasicLimits), ('io', IOCounters), ('process_memory', C.c_size_t),
                ('job_memory', C.c_size_t), ('peak_process', C.c_size_t), ('peak_job', C.c_size_t)]

K.CreateJobObjectW.argtypes = [C.c_void_p, W.LPCWSTR]
K.CreateJobObjectW.restype = W.HANDLE
K.SetInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD]
K.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
K.TerminateJobObject.argtypes = [W.HANDLE, W.UINT]
K.CloseHandle.argtypes = [W.HANDLE]
K.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
K.CreateMutexW.restype = W.HANDLE
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.GetExitCodeProcess.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
K.QueryInformationJobObject.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p]
K.SetProcessWorkingSetSizeEx.argtypes = [W.HANDLE, C.c_size_t, C.c_size_t, W.DWORD]

def enable_working_set_privilege():
    # This privilege is present in ordinary user tokens; enabling it needs no UAC.
    adv = C.WinDLL('advapi32', use_last_error=True)
    class Luid(C.Structure):
        _fields_ = [('low', W.DWORD), ('high', W.LONG)]
    class TokenPrivileges(C.Structure):
        _fields_ = [('count', W.DWORD), ('luid', Luid), ('attributes', W.DWORD)]
    adv.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    adv.LookupPrivilegeValueW.argtypes = [W.LPCWSTR, W.LPCWSTR, C.POINTER(Luid)]
    adv.AdjustTokenPrivileges.argtypes = [W.HANDLE, W.BOOL, C.c_void_p, W.DWORD, C.c_void_p, C.c_void_p]
    token = W.HANDLE()
    if not adv.OpenProcessToken(W.HANDLE(-1), 0x28, C.byref(token)): raise C.WinError(C.get_last_error())
    try:
        value = TokenPrivileges(); value.count = 1; value.attributes = 2
        if not adv.LookupPrivilegeValueW(None, 'SeIncreaseWorkingSetPrivilege', C.byref(value.luid)): raise C.WinError(C.get_last_error())
        C.set_last_error(0)
        if not adv.AdjustTokenPrivileges(token, False, C.byref(value), 0, None, None) or C.get_last_error(): raise C.WinError(C.get_last_error())
    finally:
        K.CloseHandle(token)

def cap_job_processes(job, capped, max_gib):
    data = C.create_string_buffer(8192)
    if not K.QueryInformationJobObject(job, 3, data, len(data), None): raise C.WinError(C.get_last_error())
    count = C.cast(C.byref(data, 4), C.POINTER(W.DWORD)).contents.value
    pids = C.cast(C.byref(data, 8), C.POINTER(C.c_size_t))
    current = {int(pids[i]) for i in range(count)}
    capped.intersection_update(current)
    for pid in current:
        # HIP may change the process working-set limit after allocating host
        # buffers. Reapply it rather than treating a once-capped PID as bounded.
        handle = K.OpenProcess(0x1100, False, pid)
        if not handle: continue  # A short-lived helper may already have exited.
        try:
            if not K.SetProcessWorkingSetSizeEx(handle, 16 * 1024 ** 2, max_gib * GIB, 0x4):
                raise C.WinError(C.get_last_error())
            capped.add(pid)
        finally:
            K.CloseHandle(handle)

def available():
    m = Memory(); m.length = C.sizeof(m)
    if not K.GlobalMemoryStatusEx(C.byref(m)):
        raise C.WinError(C.get_last_error())
    return m.available

def request(port, path='/health', method='GET', timeout=2):
    try:
        req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=b'{}' if method == 'POST' else None,
                                     headers={'Content-Type': 'application/json'}, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except Exception:
        return None

def alive(pid):
    handle = K.OpenProcess(0x1000, False, int(pid))
    if not handle: return False
    try:
        code = W.DWORD()
        return bool(K.GetExitCodeProcess(handle, C.byref(code))) and code.value == 259
    finally:
        K.CloseHandle(handle)

def leases(model):
    result = []
    for path in RUNTIME.glob(f'{model}.lease.*.json'):
        try:
            value = json.loads(path.read_text())
            if alive(value['pid']): result.append(path)
            else: path.unlink(missing_ok=True)
        except (ValueError, KeyError, OSError):
            continue
    return result

def preflight(model):
    if os.environ.get('LOCALAI_STRATA_GUARDED') != '1':
        raise RuntimeError('Start Strata with its run-*.bat launcher so the Windows resource guard is active.')
    free = available() / GIB
    needed = MODELS[model][2]
    if free < needed:
        raise RuntimeError(f'{model} load refused: {free:.1f} GiB RAM available; need {needed} GiB to begin a guarded load. '
                           'Unload other models or close memory-heavy apps. Runtime working-set limits and the 6 GiB physical-RAM floor remain enforced.')
    for other, (_, port, _) in MODELS.items():
        health = request(port)
        if other != model and health and health.get('loaded'):
            raise RuntimeError(f'{other} is still loaded; unload it before loading this model.')
    studio = request(1234, '/api/v0/models')
    if studio and any(m.get('state') == 'loaded' for m in studio.get('data', [])):
        raise RuntimeError('An LM Studio model is loaded. Unload it before loading Strata.')
    share = ROOT / 'apps' / 'ComfyUI' / 'share_gpu.py'
    if share.exists():
        subprocess.run([str(ROOT / 'apps' / 'ComfyUI' / 'python_embeded' / 'python.exe'), '-s', str(share), '--comfy'], check=True, timeout=30)
    print(f'[desktop guard] Load admitted: {free:.1f} GiB available; model {model}.', flush=True)

def state(model, **values):
    RUNTIME.mkdir(parents=True, exist_ok=True)
    values.update(pid=os.getpid(), model=model, updated=time.time())
    path = RUNTIME / f'{model}.status.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(values, indent=2))
    temporary.replace(path)

def supervise(model, pi_owned):
    ws_gib = 6 if model == 'qwen36' else 12
    RUNTIME.mkdir(parents=True, exist_ok=True)
    mutex = K.CreateMutexW(None, True, r'Local\LocalAI-Strata-Desktop-Guard')
    if not mutex: raise C.WinError(C.get_last_error())
    if C.get_last_error() == 183:
        K.CloseHandle(mutex)
        raise RuntimeError('A guarded Strata server is already running. Use stop-strata before switching servers.')
    job = None
    proc = None
    reason = 'server exited'
    stop_path = RUNTIME / f'{model}.stop'
    stop_path.unlink(missing_ok=True)
    log = (ROOT / 'logs' / f'strata-{model}-guarded.log').open('a', buffering=1)
    try:
        job = K.CreateJobObjectW(None, None)
        if not job: raise C.WinError(C.get_last_error())
        limits = ExtendedLimits()
        # Kill every descendant when this supervisor closes, including abrupt console closure.
        # Working-set limits include mapped pages; the independent physical-memory floor also
        # covers pinned GPU/driver allocations that Windows may keep outside a normal working set.
        limits.basic.flags = 0x2000 | 0x0200
        limits.job_memory = 40 * GIB  # Commit includes driver backing; distinct from physical RAM.
        if not K.SetInformationJobObject(job, 9, C.byref(limits), C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
        enable_working_set_privilege()
        cfg, port, _ = MODELS[model]
        env = os.environ.copy()
        env['LOCALAI_STRATA_GUARDED'] = '1'
        env['PYTHONUNBUFFERED'] = '1'
        proc = subprocess.Popen([str(STRATA / '.venv' / 'Scripts' / 'python.exe'), str(STRATA / 'serve' / 'server.py'),
                                 '--engine', 'strata', '--config', str(STRATA / cfg), '--port', str(port)],
                                cwd=STRATA, env=env, stdout=log, stderr=log,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
        if not K.AssignProcessToJobObject(job, W.HANDLE(int(proc._handle))):
            proc.terminate(); proc.wait(timeout=5)
            raise C.WinError(C.get_last_error())
        state(model, state='running', server_pid=proc.pid, port=port, pi_owned=pi_owned,
              working_set_limit_gib=ws_gib, commit_limit_gib=40, free_ram_floor_gib=6)
        print(f'Strata {model}: http://127.0.0.1:{port}; guarded. Ctrl+C stops server and engine.', flush=True)
        print(f'Windows/browser RAM floor: 6 GiB. Per-process working set: {ws_gib} GiB. Idle model unload: 300 s.', flush=True)
        empty_since = None
        low_since = None
        started = time.monotonic()
        capped = set()
        min_free = available() / GIB
        next_status = 0
        while proc.poll() is None:
            cap_job_processes(job, capped, ws_gib)
            now = time.monotonic()
            free = available() / GIB
            min_free = min(min_free, free)
            if now >= next_status:
                state(model, state='running', server_pid=proc.pid, port=port, pi_owned=pi_owned,
                      working_set_limit_gib=ws_gib, commit_limit_gib=40, free_ram_floor_gib=6,
                      minimum_available_ram_gib=round(min_free, 3), available_ram_gib=round(free, 3), capped_pids=sorted(capped))
                next_status = now + 2
            if free < 6:
                low_since = now if low_since is None else low_since
                if now - low_since >= 0.5:
                    reason = f'RAM safety stop: only {free:.2f} GiB available (6 GiB floor)'
                    break
            else:
                low_since = None
            if stop_path.exists():
                reason = 'stop-strata requested'
                break
            if pi_owned:
                if leases(model): empty_since = None
                else:
                    empty_since = now if empty_since is None else empty_since
                    if now - empty_since > 8 and now - started > 15:
                        reason = 'no live Pi session leases remain'
                        break
            time.sleep(0.5)
    except KeyboardInterrupt:
        reason = 'Ctrl+C'
    except Exception as error:
        reason = f'resource guard failed safely: {error}'
        raise
    finally:
        if proc and proc.poll() is None:
            # A memory emergency must release memory immediately; normal stops first try QUIT via /unload.
            if not reason.startswith('RAM safety'):
                request(MODELS[model][1], '/unload?wait=3', method='POST', timeout=4)
            if job: K.TerminateJobObject(job, 0)
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
        if job: K.CloseHandle(job)
        K.CloseHandle(mutex)
        stop_path.unlink(missing_ok=True)
        log.write(f'\n[desktop guard] {reason}\n'); log.close()
        state(model, state='stopped', reason=reason, server_exit=proc.returncode if proc else None,
              minimum_available_ram_gib=round(min_free, 3) if 'min_free' in locals() else None)
        print(f'Strata released: {reason}.', flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=MODELS, default='iq2xs')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--pi-owned', action='store_true')
    args = parser.parse_args()
    if args.stop:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        for name in MODELS: (RUNTIME / f'{name}.stop').touch()
        print('Requested shutdown of managed Strata servers and engines.')
    elif args.check: preflight(args.model)
    else: supervise(args.model, args.pi_owned)

if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(f'[desktop guard] {error}', file=sys.stderr, flush=True)
        sys.exit(1)
