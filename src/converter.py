"""Convert Fluent CFF files with Fluent itself; verify before publishing outputs.

Requires ansys-fluent-core and numpy, plus a licensed Fluent installation.
This project was verified with Fluent 2024 R1 / PyFluent 0.37.2.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import tempfile
import shutil

import numpy as np
import ansys.fluent.core as pyfluent

HDF5_MAGIC = b'\x89HDF\r\n\x1a\n'


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def natural_key(path):
    return [int(x) if x.isdigit() else x.lower()
            for x in re.split(r'(\d+)', str(path))]


def discover(root):
    cases = sorted(root.glob('*.cas.h5'), key=natural_key)
    data = sorted(root.glob('*.dat.h5'), key=natural_key)
    if not cases:
        raise ValueError(f'No *.cas.h5 files in {root}')
    pairs = {c: [] for c in cases}
    for d in data:
        stem = d.name[:-7]
        candidates = [c for c in cases if stem == c.name[:-7]
                      or stem.startswith(c.name[:-7] + '-')]
        if not candidates:
            raise ValueError(f'No matching case for {d.name}')
        # Autosave case number precedes the step number in these filenames.
        longest = max(len(c.name) for c in candidates)
        candidates = [c for c in candidates if len(c.name) == longest]
        if len(candidates) != 1:
            raise ValueError(f'Ambiguous case for {d.name}: {candidates}')
        pairs[candidates[0]].append(d)
    jobs = []
    for c in cases:
        for d in pairs[c] or [None]:
            jobs.append((c, d, (d or c).name[:-7]))
    stems = [j[2] for j in jobs]
    if len(stems) != len(set(stems)):
        raise ValueError('Duplicate output filenames')
    for p in cases + data:
        with p.open('rb') as stream:
            if stream.read(8) != HDF5_MAGIC:
                raise ValueError(f'Not an HDF5 file: {p}')
    return jobs


def snapshot(s, has_data):
    info = s.fields.solution_variable_info
    zi = info.get_zones_info()
    topology = {z: {'id': zi[z].zone_id, 'count': zi[z].count,
                    'type': zi[z].zone_type, 'thread_type': zi[z].thread_type}
                for z in zi.zone_names}
    arrays = {}
    cell_zones = [z for z in zi.zone_names if zi[z].zone_type in ('fluid', 'solid')]
    for domain in zi.domains:
        for zone in cell_zones:
            if domain != 'mixture' and zi[zone].zone_type != 'fluid':
                continue
            wanted = ['SV_CENTROID', 'SV_VOLUME'] if domain == 'mixture' else []
            if has_data:
                if domain == 'mixture':
                    wanted += ['SV_T']
                    if zi[zone].zone_type == 'fluid':
                        wanted += ['SV_P', 'SV_U', 'SV_V', 'SV_W']
                else:
                    wanted += ['SV_VOF']
            available = info.get_variables_info(
                zone_names=[zone], domain_name=domain).solution_variables
            for var in wanted:
                if var not in available:
                    continue
                arr = s.fields.solution_variable_data.get_data(
                    variable_name=var, zone_names=[zone], domain_name=domain)[zone]
                arrays['|'.join((domain, zone, var))] = np.asarray(arr).copy()
    if not arrays:
        raise RuntimeError('No cell arrays available for verification')
    if has_data and not any(k.endswith('|SV_P') for k in arrays):
        raise RuntimeError('Pressure field missing; data verification cannot pass')
    clock = s.scheme.eval("(list (rpgetvar 'flow-time) (rpgetvar 'time-step))")
    return {'zones': topology, 'domains': sorted(zi.domains), 'time': clock}, arrays


def output_names(c, d, stem, jobs):
    # A shared CASE must not be overwritten by the next DAT's verified CASE.
    folder = Path(stem) if sum(case == c for case, _, _ in jobs) > 1 else Path()
    return [folder / c.name[:-3]] + ([folder / d.name[:-3]] if d else [])


def array_summary(arrays):
    result = {}
    for key, a in arrays.items():
        result[key] = {'count': int(a.size), 'dtype': str(a.dtype),
                       'min': float(np.min(a)), 'max': float(np.max(a)),
                       'sha256': hashlib.sha256(a.tobytes()).hexdigest()}
    return result


def compare(before, after):
    meta_a, arrays_a = before
    meta_b, arrays_b = after
    if meta_a != meta_b:
        raise RuntimeError(f'Mesh/domain/time mismatch: {meta_a} != {meta_b}')
    if arrays_a.keys() != arrays_b.keys():
        raise RuntimeError('Available verification fields changed on readback')
    checks = {}
    for name, a in arrays_a.items():
        b = arrays_b[name]
        if a.shape != b.shape or not np.array_equal(a, b, equal_nan=True):
            err = float(np.max(np.abs(a - b))) if a.shape == b.shape else None
            raise RuntimeError(f'Field changed: {name}; max_abs_error={err}')
        checks[name] = {'exact_equal': True, 'max_abs_error': 0.0}
    return checks


def check_legacy(path):
    if not path.is_file() or path.stat().st_size < 100:
        raise RuntimeError(f'Missing or empty output: {path}')
    with path.open('rb') as stream:
        header = stream.read(128)
    if header.startswith(HDF5_MAGIC) or not header.lstrip().startswith(b'('):
        raise RuntimeError(f'Output is not a Fluent legacy section file: {path}')


def save_report(path, report):
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False),
                   encoding='utf-8')
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--version', default='24.1.0')
    parser.add_argument('--dimension', type=int, choices=[2, 3], default=2)
    parser.add_argument('--limit', type=int, help='Convert first N discovered jobs')
    parser.add_argument('--stop-file', type=Path)
    parser.add_argument('--resume', action='store_true', help='Skip hash-matching verified outputs')
    parser.add_argument('--list', action='store_true', help='Show mapping without launching Fluent')
    args = parser.parse_args()
    root = args.input.resolve()
    output = (args.output or root / 'legacy_cas_dat').resolve()
    if output == root:
        parser.error('Use a separate output directory')
    if args.limit is not None and args.limit < 1:
        parser.error('--limit must be positive')
    jobs = discover(root)
    if args.limit:
        jobs = jobs[:args.limit]
    if args.list:
        for c, d, stem in jobs:
            print(f'{c.name} + {d.name if d else "[CASE ONLY]"} -> '+ ' / '.join(str(p) for p in output_names(c,d,stem,jobs)))
        return 0
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'conversion_report.json'
    previous = {}
    if args.resume and report_path.exists():
        previous = json.loads(report_path.read_text(encoding='utf-8'))
        if previous.get('naming_policy') != 'preserve-source-v1':
            raise ValueError('此目录包含旧版转换报告。保留原名模式请使用新的输出目录；旧结果不会被修改。')
    old = {j['stem']: j for j in previous.get('jobs', [])}
    pending, completed = [], []
    for c, d, stem in jobs:
        sources = {p.name: sha256(p) for p in [c, d] if p}
        record = old.get(stem)
        targets = [output / name for name in output_names(c,d,stem,jobs)]
        if (record and record.get('status') == 'verified'
                and set(record.get('output_sha256',{})) == {p.relative_to(output).as_posix() for p in targets}
                and record.get('source_sha256') == sources
                and all(p.is_file() and record.get('output_sha256', {}).get(p.relative_to(output).as_posix())
                        == sha256(p) for p in targets)):
            completed.append(record)
            print(f'SKIP VERIFIED {stem}', flush=True)
            continue
        if any(p.exists() for p in targets):
            raise FileExistsError(f'Existing/unverified output for {stem}; choose a new --output directory')
        pending.append((c, d, stem, sources))
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    work = output / '_logs' / stamp
    work.mkdir(parents=True, exist_ok=True)
    report = {'naming_policy':'preserve-source-v1','created_local': datetime.now().isoformat(), 'fluent_version': args.version,
              'dimension': args.dimension, 'precision': 'double', 'processors': 1,
              'input_directory': str(root), 'output_directory': str(output),
              'validation': 'Full-cell exact array comparison after CAS/DAT readback; mesh zone metadata and flow time/step comparison; header and SHA256 checks',
              'surface_limitation': 'Legacy format does not retain some interpolated surface values; retain original H5 files.',
              'jobs': completed, 'status': 'running', 'log_directory': str(work)}
    if previous.get('naming'):
        report['naming'] = previous['naming']
    save_report(report_path, report)
    stage = Path(tempfile.mkdtemp(prefix='FluentConvert_'))
    if not str(stage).isascii():
        raise RuntimeError('Fluent staging requires an ASCII TEMP path; set TEMP to an English path.')
    s = None
    try:
        if pending:
            print('Launching a separate Fluent session (2ddp, one processor)...', flush=True)
            s = pyfluent.launch_fluent(product_version=args.version, mode='solver',
                    dimension=args.dimension, precision='double', processor_count=1,
                    ui_mode='no_gui', cwd=str(stage), start_timeout=120,
                    cleanup_on_exit=True, start_transcript=False)
            s.transcript.start(file_name=str(stage / 'fluent_conversion.trn'),
                               write_to_stdout=False)
        for number, (c, d, stem, source_hashes) in enumerate(pending, 1):
            if args.stop_file and args.stop_file.exists():
                report['status'] = 'stopped'
                save_report(report_path, report)
                print('STOPPED: current completed outputs retained', flush=True)
                return 2
            started = time.monotonic()
            print(f'[{number}/{len(pending)}] READ {c.name}'
                  + (f' + {d.name}' if d else ' [case only]'), flush=True)
            staged_case = stage / 'input.cas.h5'
            shutil.copyfile(c, staged_case)
            s.settings.file.read_case(file_name=str(staged_case))
            if d:
                staged_data = stage / 'input.dat.h5'
                shutil.copyfile(d, staged_data)
                s.settings.file.read_data(file_name=str(staged_data))
            before = snapshot(s, bool(d))
            s.tui.file.cff_files('no')
            s.tui.file.binary_legacy_files('yes')
            # Copying verified outputs leaves the staging files behind. Never reuse
            # a filename: Fluent may decline an overwrite prompt and leave old data.
            job_stage = stage / ('job_'+str(number).zfill(6))
            job_stage.mkdir()
            cas = job_stage / 'result.cas'
            dat = job_stage / 'result.dat'
            s.tui.file.write_case(str(cas))
            if d:
                s.tui.file.write_data(str(dat))
            targets = [cas] + ([dat] if d else [])
            for p in targets:
                check_legacy(p)
            # Reading the case rebuilds the mesh/model before loading its data.
            s.settings.file.read_case(file_name=str(cas))
            if d:
                s.settings.file.read_data(file_name=str(dat))
            checks = compare(before, snapshot(s, bool(d)))
            for p in [c, d]:
                if p and sha256(p) != source_hashes[p.name]:
                    raise RuntimeError(f'Source changed during conversion: {p}')
            names=output_names(c,d,stem,jobs)
            sizes = {name.as_posix(): p.stat().st_size for name,p in zip(names,targets)}
            hashes = {name.as_posix(): sha256(p) for name,p in zip(names,targets)}
            for p,name in zip(targets,names):
                dest=output/name;dest.parent.mkdir(parents=True,exist_ok=True)
                # Exclusive creation works across TEMP/output drives without overwriting.
                with p.open('rb') as source, dest.open('xb') as target:
                    shutil.copyfileobj(source,target,4*1024*1024)
                if sha256(dest)!=hashes[name.as_posix()]:
                    raise RuntimeError(f'Output copy verification failed: {dest}')
            record = {'stem': stem, 'case_source': c.name,
                      'data_source': d.name if d else None,
                      'status': 'verified', 'source_sha256': source_hashes,
                      'output_sha256': hashes, 'output_bytes': sizes,
                      'mesh_and_time': before[0], 'source_arrays': array_summary(before[1]),
                      'readback_checks': checks,
                      'seconds': round(time.monotonic() - started, 2)}
            report['jobs'].append(record)
            save_report(report_path, report)
            print(f'[{number}/{len(pending)}] VERIFIED {stem}; '
                  f'{len(checks)} complete arrays EXACT; {record["seconds"]} s', flush=True)
            # Limit scratch space after the verified copies and journal are durable.
            for temporary in targets:
                try:temporary.unlink()
                except OSError:pass  # A locked file is isolated and cannot affect later jobs.
        report['status'] = 'complete'
        report['counts'] = {'cas': len(report['jobs']),
                            'dat': sum(j['data_source'] is not None for j in report['jobs'])}
        save_report(report_path, report)
        print('COMPLETE ' + json.dumps(report['counts']), flush=True)
        return 0
    except BaseException as exc:
        report['status'] = 'failed'
        report['error'] = repr(exc)
        save_report(report_path, report)
        raise
    finally:
        if s is not None:
            s.exit()
        for log in stage.glob('*.trn'):
            shutil.copy2(log, work / log.name)
        # Fluent may keep its auto-transcript open briefly after exit.
        # Restrict cleanup to the exact temporary child created by this run.
        if stage.resolve().parent == Path(tempfile.gettempdir()).resolve() and stage.name.startswith('FluentConvert_'):
            shutil.rmtree(stage, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
