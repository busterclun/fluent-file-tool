"""Bounded Windows installation discovery. Never installs software or launches Fluent."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ENV_KEYS = ('fluent_root', 'version', 'python')


def unique_paths(paths):
    seen = set()
    for value in paths:
        if not value:
            continue
        path = Path(os.path.expandvars(str(value))).absolute()
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            yield path


def children(path, pattern):
    try:
        return sorted(Path(path).glob(pattern))[:80]
    except OSError:
        return []


def registry_paths():
    """Read registered Python installations and ANSYS uninstall locations."""
    python, fluent = [], []
    try:
        import winreg
    except ImportError:
        return python, fluent
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for keyname, kind in ((r'SOFTWARE\Python\PythonCore', 'python'),
                                  (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', 'fluent')):
                try:
                    with winreg.OpenKey(hive, keyname, 0, winreg.KEY_READ | view) as key:
                        for index in range(min(winreg.QueryInfoKey(key)[0], 1500)):
                            subname = winreg.EnumKey(key, index)
                            try:
                                with winreg.OpenKey(key, subname + (r'\InstallPath' if kind == 'python' else '')) as sub:
                                    if kind == 'python':
                                        python.append(Path(winreg.QueryValueEx(sub, '')[0]) / 'python.exe')
                                    elif 'ansys' in str(winreg.QueryValueEx(sub, 'DisplayName')[0]).lower():
                                        fluent.append(Path(winreg.QueryValueEx(sub, 'InstallLocation')[0]))
                            except OSError:
                                continue
                except OSError:
                    continue
    return python, fluent


def discover_paths(config, base):
    registered_python, registered_fluent = registry_paths()
    drives = [Path(f'{letter}:\\') for letter in 'CDEFGHIJKLMNOPQRSTUVWXYZ' if Path(f'{letter}:\\').is_dir()]
    roots = [config.get('fluent_root')]
    roots += [v for k, v in os.environ.items() if re.fullmatch(r'AWP_ROOT\d{3}', k, re.I)]
    install_parents = registered_fluent + [d / p for d in drives for p in ('Program Files/ANSYS Inc', 'ANSYS Inc', 'ANSYS')]
    for parent in install_parents:
        roots.append(parent);roots.extend(children(parent, 'v[0-9][0-9][0-9]'))
    installations = []
    for root in unique_paths(roots):
        if not (root / 'fluent/ntbin/win64/fluent.exe').is_file():
            continue
        match = re.fullmatch(r'v(\d{2})([12])', root.name, re.I)
        version = f'{match[1]}.{match[2]}.0' if match else config.get('version', '') if str(root).casefold() == str(config.get('fluent_root', '')).casefold() else ''
        if re.fullmatch(r'\d{2}\.[12]\.0', version):
            installations.append(dict(fluent_root=str(root), version=version))
    python = [config.get('python')]
    selected = Path(config['python']) if config.get('python') else None
    search_roots = []
    if selected:
        # Windows venv: project/.venv/Scripts/python.exe; include sibling venvs.
        search_roots.extend([selected.parent, selected.parent.parent, selected.parent.parent.parent])
    search_roots += [Path(base), Path(base).parent, Path.cwd(), Path.home()]
    for drive in drives:
        search_roots += children(drive / 'CODEX', '*')
    for root in unique_paths(search_roots):
        python += [root / 'Scripts/python.exe', root / 'python.exe']
        for pattern in ('.venv*', 'venv*', '*env', 'envs/*', '.virtualenvs/*'):
            for env in children(root, pattern):
                python += [env / 'Scripts/python.exe', env / 'python.exe']
    python += registered_python
    for root in (Path.home() / 'miniconda3', Path.home() / 'anaconda3', Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Programs/Python'):
        python += [root / 'python.exe']
        for env in children(root, 'envs/*') + children(root, 'Python*'):
            python.append(env / 'python.exe')
    python += [Path(p) / 'python.exe' for p in os.environ.get('PATH', '').split(os.pathsep) if p]
    candidates = [p for p in unique_paths(python) if p.name.lower() == 'python.exe' and p.is_file()
                  and 'windowsapps' not in str(p).lower()]
    return installations, candidates[:32]


def probe_python(executable, probe_script, cancel=None):
    if cancel is not None and cancel.is_set():
        return None
    try:
        process = subprocess.Popen([str(executable), '-u', str(probe_script), '--describe-json'],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                                env={**os.environ, 'PYTHONUTF8':'1', 'PYTHONIOENCODING':'utf-8'},
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + 8
        while True:
            if time.monotonic() >= deadline or (cancel is not None and cancel.is_set()):
                process.kill();process.communicate()
                return None
            try:
                stdout, _ = process.communicate(timeout=.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            return None
        for line in reversed(stdout.splitlines()):
            try:
                data = json.loads(line)
                if isinstance(data, dict) and isinstance(data.get('supported'), list):
                    return dict(data, executable=str(executable))
            except ValueError:
                continue
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def detect(config, base, probe_script, cancel=None):
    installations, candidates = discover_paths(config, base)
    if not installations:
        return dict(options=[], installations=[], checked=0, reason='未找到 Fluent 安装位置。可手动选择版本根目录，再点“重新检索”。')
    with ThreadPoolExecutor(max_workers=4) as pool:
        probes = list(pool.map(lambda p: probe_python(p, probe_script, cancel), candidates))
    options = []
    for install in installations:
        for probe in probes:
            if probe and install['version'] in probe['supported']:
                options.append(dict(**install, python=probe['executable'], pyfluent=probe['pyfluent'], python_version=probe['python']))
    def rank(item):
        root_same = item['fluent_root'].casefold() == config.get('fluent_root', '').casefold()
        python_same = item['python'].casefold() == config.get('python', '').casefold()
        version_same = item['version'] == config.get('version')
        return (not (root_same and python_same and version_same), not root_same, not version_same,
                not python_same, tuple(-int(p) for p in item['version'].split('.')), item['python'].casefold())
    options.sort(key=rank)
    return dict(options=options, installations=installations, checked=len(candidates),
                reason='' if options else '找到了 Fluent，但未找到支持该版本且包含 NumPy 的 Python 环境。请手动选择兼容的 python.exe，再点“重新检索”。')
