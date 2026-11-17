"""Strict, metadata-only Fluent naming transactions. No Fluent dependency or file copying."""
from __future__ import annotations

import collections
from contextlib import contextmanager
import csv
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import uuid
import hashlib

_filesystem_cache = {}

def report_progress(callback,phase,done=0,total=0,current=''):
    if callback is not None:
        try:callback(dict(phase=phase,done=done,total=total,current=current))
        except Exception:pass  # Presentation must not change transaction behavior.

def filesystem_type(path, device):
    if os.name != 'nt':return 'NTFS'
    key=(str(Path(path).absolute().anchor),device)
    if key not in _filesystem_cache:
        api=ctypes.WinDLL('kernel32',use_last_error=True)
        volume=ctypes.create_unicode_buffer(32768);name=ctypes.create_unicode_buffer(256)
        if not api.GetVolumePathNameW(ctypes.c_wchar_p(str(Path(path).absolute())),volume,len(volume)):
            raise ctypes.WinError(ctypes.get_last_error())
        if not api.GetVolumeInformationW(volume,None,0,None,None,None,name,len(name)):
            raise ctypes.WinError(ctypes.get_last_error())
        if name.value.upper() not in ('NTFS','REFS','EXFAT','FAT','FAT32'):
            raise OSError('暂不支持此文件系统的安全改名：'+name.value)
        _filesystem_cache[key]=name.value.upper()
    return _filesystem_cache[key]

EXT = re.compile(r'(\.cas\.h5|\.dat\.h5|\.cas|\.dat)$', re.I)
STEP = re.compile(r'^(.*)-([0-9]+)$')
NOTICE = '仅核验文件名和文件元数据，未读取 Fluent 内部实际求解时间步；未提供预期保存间隔，不能断言时间序列完整。'


def split_name(name):
    match = EXT.search(name)
    if not match:
        return None
    ext = match[0]
    return name[:match.start()], ext, 'cas' if ext.lower().startswith('.cas') else 'dat', ext.lower().endswith('.h5')


def fingerprint(path):
    s = Path(path).lstat()
    # FAT-family file indexes may change on rename. They are not stable identities.
    stable_id=filesystem_type(path,s.st_dev) in ('NTFS','REFS')
    return dict(size=s.st_size, mtime_ns=s.st_mtime_ns, device=s.st_dev, inode=s.st_ino if stable_id else 0)

def content_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def matches_row(path,row):
    return fingerprint(path)=={k:row[k] for k in ('size','mtime_ns','device','inode')} and (not row.get('content_sha256') or content_hash(path)==row['content_sha256'])


def linked(path):
    s = path.lstat()
    return stat.S_ISLNK(s.st_mode) or bool(getattr(s, 'st_file_attributes', 0) & 0x400)


def inventory(root, recursive):
    """Includes other file types for change detection; does not follow reparse points."""
    result = {}
    def visit(folder):
        for p in sorted(folder.iterdir(), key=lambda x: (x.name.casefold(), x.name)):
            rel = p.relative_to(root).as_posix()
            if linked(p):
                result[rel] = dict(kind='link', **fingerprint(p))
            elif p.is_dir():
                result[rel] = dict(kind='directory')
                if recursive:
                    visit(p)
            elif p.is_file():
                result[rel] = dict(kind='file', **fingerprint(p))
            else:
                result[rel] = dict(kind='special')
    visit(root)
    return result


def prefix_error(prefix):
    if not prefix or not prefix.strip():
        return '统一前缀不能为空。'
    if re.search(r'[<>:"/\\|?*\x00-\x1f]', prefix) or prefix.endswith((' ', '.')) or prefix in ('.', '..'):
        return '前缀含 Windows 非法字符，或以空格、句点结尾。'
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?', prefix, re.I):
        return '前缀不能使用 Windows 保留设备名。'
    return None


def step_summary(steps):
    nums = sorted(set(int(x) for x in steps))
    groups = []
    for a, b in zip(nums, nums[1:]):
        delta = b - a
        if groups and groups[-1]['interval'] == delta:
            groups[-1]['end'] = b
            groups[-1]['count'] += 1
        else:
            groups.append(dict(start=a, end=b, interval=delta, count=1))
    return dict(step_count=len(nums), step_range=[nums[0], nums[-1]] if nums else [], intervals=groups)


def preview(directory, prefix, recursive=False, initial_step=None):
    root = Path(directory).absolute()
    issues = []
    def issue(code, message, paths=()):
        issues.append(dict(code=code, message=message, paths=list(paths)))
    plan = dict(schema=1, batch=uuid.uuid4().hex, created_at=datetime.now(timezone.utc).isoformat(),
                root=str(root), prefix=prefix, recursive=bool(recursive), initial_step=initial_step,
                mapping=[], issues=issues, notice=NOTICE)
    if initial_step is not None and (not isinstance(initial_step, str) or
                                    not re.fullmatch(r'[0-9]{1,100}', initial_step)):
        issue('initial_step', '初始编号必须填写非负整数（仅数字，最多 100 位）。')
        initial_step = None
    error = prefix_error(prefix)
    if error:
        issue('prefix', error)
    if not root.is_dir():
        issue('directory', '目录不存在或不是文件夹。', [str(root)])
        plan.update(snapshot={}, summary=dict(scanned_files=0, fluent_files=0, pair_count=0, unchanged=0, changes=0, **step_summary([])))
        return plan
    # Resolve the root once; refuse symlink/junction traversal inside the chosen tree.
    root = root.resolve(); plan['root'] = str(root)
    try:
        snap = inventory(root, recursive)
    except OSError as exc:
        issue('scan_failed', f'扫描失败：{exc}')
        snap = {}
    plan['snapshot'] = snap
    files = {p: split_name(Path(p).name) for p, s in snap.items() if split_name(Path(p).name) and s['kind'] == 'file'}
    for p, s in snap.items():
        if Path(p).name.startswith('.fluent-rename-') and Path(p).name.endswith('.tmp'):
            issue('pending_recovery', '发现未恢复的命名事务临时文件，请先通过原批次记录恢复。', [p])
        if s['kind'] in ('link', 'special') and (recursive or split_name(Path(p).name)):
            issue('unsafe_path', '不支持符号链接、目录联接或特殊文件；未跟随该路径。', [p])
    case_lookup = collections.defaultdict(list)
    for p in files:
        case_lookup[p.casefold()].append(p)
    for matches in case_lookup.values():
        if len(matches) > 1:
            issue('case_collision', '存在仅大小写不同的路径，不能安全处理。', matches)
    used = collections.defaultdict(list)
    steps = collections.defaultdict(list)
    tokens = []
    pairs = []
    families = set()
    numbered_tokens = [m[2] for stem, ext, kind, h5 in files.values()
                       if kind == 'dat' and (m := STEP.fullmatch(stem)) and m[1] and len(m[2]) <= 100]
    padded_widths = {len(t) for t in numbered_tokens if len(t) > 1 and t.startswith('0')}
    # Padding is only supplied for the explicitly assigned initial number.
    # Existing numbered filenames remain unchanged and undergo the usual checks.
    initial_token = initial_step
    if initial_token is not None:
        width = next(iter(padded_widths)) if len(padded_widths) == 1 else (5 if not numbered_tokens else 0)
        initial_token = initial_token.zfill(width)
    assigned_initial = []
    for dat, (stem, ext, kind, h5) in files.items():
        if kind != 'dat':
            continue
        match = STEP.fullmatch(stem)
        is_initial = not match or not match[1]
        if is_initial:
            if initial_token is None:
                issue('unrecognized_step', 'DAT 没有可识别的时间步；若确认是初始帧，请启用“将无编号配对作为初始帧”并指定编号。', [dat])
                continue
            base, token = stem, initial_token
        else:
            base, token = match.groups()
        if len(token) > 100:
            issue('unrecognized_step', '时间步数字过长，无法可靠处理。', [dat])
            continue
        steps[int(token)].append(dat); tokens.append(token); families.add(h5)
        cas_ext = '.cas.h5' if h5 else '.cas'
        parent = Path(dat).parent
        candidates = set()
        for cas_stem in (base, stem):
            candidate = (parent / (cas_stem + cas_ext)).as_posix()
            candidates.update(case_lookup.get(candidate.casefold(), []))
        if len(candidates) != 1:
            if candidates:
                issue('ambiguous_case', 'DAT 同时匹配多个 CASE，不能猜测。', [dat, *sorted(candidates)])
            else:
                wrong_ext = '.cas' if h5 else '.cas.h5'
                wrong = [p for name in (base, stem) for p in case_lookup.get((parent / (name + wrong_ext)).as_posix().casefold(), [])]
                issue('format_mismatch' if wrong else 'missing_case',
                      'CASE/DAT 扩展格式不匹配。' if wrong else '缺少可可靠配对的 CASE。', [dat, *wrong])
            continue
        cas = next(iter(candidates))
        if is_initial:
            assigned_initial.append(dict(case=cas, data=dat, step=token))
        used[cas].append(dat); pairs.append((cas, dat, token))
        for source in (cas, dat):
            _, original_ext, file_kind, _ = files[source]
            target = (Path(source).parent / f'{prefix}-{token}{original_ext}').as_posix()
            if len(Path(target).name.encode('utf-16-le')) // 2 > 255:
                issue('name_too_long', '目标文件名超过 Windows 255 字符上限。', [source, target])
            plan['mapping'].append(dict(old=source, new=target, step=token, type=file_kind,
                                        extension=original_ext, **{k:v for k,v in snap[source].items() if k != 'kind'}))
    for cas, data in used.items():
        if len(data) > 1:
            issue('case_shared', '多个 DAT 争用同一个 CASE。', [cas, *data])
    for cas, parts in files.items():
        if parts[2] == 'cas' and cas not in used:
            issue('unpaired_case', 'CASE 未可靠配对；不能把 CASE 保存序号当成时间步。', [cas])
    for number, data in steps.items():
        if len(data) > 1:
            issue('duplicate_step', f'时间步 {number} 重复（按数值比较，包括不同前导零）。', data)
    if any(len(t) > 1 and t.startswith('0') for t in tokens) and len({len(t) for t in tokens}) > 1:
        issue('padding_mismatch', '时间步前导零位宽不一致；请核对，程序不会自动补零或去零。', [p for ps in steps.values() for p in ps])
    if len(families) > 1:
        issue('mixed_formats', '本批次混有传统格式和 H5 格式，请分目录或分批处理。', list(files))
    targets = collections.defaultdict(list)
    sources = {r['old'].casefold() for r in plan['mapping']}
    for row in plan['mapping']:
        targets[row['new'].casefold()].append(row['old'])
    occupants_by_key = collections.defaultdict(list)
    for p in snap:occupants_by_key[p.casefold()].append(p)
    for target, originals in targets.items():
        if len(originals) > 1:
            issue('duplicate_target', '多个源文件映射到同一目标。', originals)
        occupants = occupants_by_key.get(target, [])
        if occupants and target not in sources:
            issue('target_exists', '目标路径已被本批次之外的文件或目录占用。', occupants)
    if not files:
        issue('no_files', '没有找到 .cas、.dat、.cas.h5 或 .dat.h5 文件。')
    plan['summary'] = dict(scanned_files=sum(s['kind'] == 'file' for s in snap.values()), fluent_files=len(files),
                           pair_count=sum(len(used[cas]) == 1 for cas, _, _ in pairs),
                           changes=sum(r['old'] != r['new'] for r in plan['mapping']),
                           unchanged=sum(r['old'] == r['new'] for r in plan['mapping']), **step_summary(tokens))
    plan['warnings'] = []
    plan['assigned_initial'] = assigned_initial
    if assigned_initial:
        plan['warnings'].append(f'{len(assigned_initial)} 组无编号配对按你指定的初始编号 {initial_token} 整理；此编号未经 Fluent 内部时间步验证。')
    if plan['summary']['changes'] and any(Path(p).name in ('conversion_report.json','rename_manifest.json') for p in snap):
        plan['warnings'].append('目录含旧转换报告。本功能只更新独立的命名对照清单，不改写旧报告中的路径；更名后不能直接用旧报告继续转换或整理。')
    return plan


def safe_path(root, relative):
    rel = Path(relative)
    if rel.is_absolute() or '..' in rel.parts or not rel.parts:
        raise ValueError(f'不安全的相对路径：{relative}')
    result = root / rel
    result.resolve().relative_to(root.resolve())
    current = result
    while current != root:
        if os.path.lexists(current) and linked(current):
            raise ValueError(f'路径包含链接：{relative}')
        current = current.parent
    return result


def move_no_replace(source, target):
    """MoveFileW is atomic and fails if the destination exists; never os.replace CFD files."""
    if os.name != 'nt':
        raise OSError('此发布版的无覆盖重命名仅支持 Windows。')
    api = ctypes.WinDLL('kernel32', use_last_error=True).MoveFileW
    api.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]; api.restype = ctypes.c_int
    def long_name(path):
        value = str(Path(path).absolute())
        if value.startswith('\\\\?\\'):
            return value
        return '\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value
    if not api(long_name(source), long_name(target)):
        raise ctypes.WinError(ctypes.get_last_error())


def write_json(path, value):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as out:
            json.dump(value, out, ensure_ascii=False, indent=2)
            out.flush(); os.fsync(out.fileno())
        os.replace(temp, path)  # Only our own small audit record, never a CFD source/target.
    finally:
        temp.unlink(missing_ok=True)


def assert_unchanged(plan):
    current = inventory(Path(plan['root']), plan['recursive'])
    if current != plan['snapshot']:
        changed = [p for p in sorted(set(current) | set(plan['snapshot'])) if current.get(p) != plan['snapshot'].get(p)]
        raise ValueError('预览后目录或文件发生变化，请重新扫描：' + '；'.join(changed))


def audit_rows(plan):
    return [dict(batch=plan['batch'], relative_directory=Path(r['old']).parent.as_posix(),
                 old_name=Path(r['old']).name, new_name=Path(r['new']).name,
                 old_path=r['old'], new_path=r['new'], step=r['step'], type=r['type'],
                 size=r['size'], mtime_ns=r['mtime_ns'],
                 modified_utc=datetime.fromtimestamp(r['mtime_ns']/1e9, timezone.utc).isoformat()) for r in plan['mapping']]


def locate_states(root, rows):
    states = []
    exact_cache = {}
    for r in rows:
        found = []; observed = []
        for rel in dict.fromkeys([r['old'], r.get('temp'), r['new']]):
            if not rel:
                continue
            try:
                p = safe_path(root, rel)
                exists = os.path.lexists(p)
                actual = fingerprint(p) if exists else None
                observed.append(dict(path=rel,exists=exists,metadata=actual))
                if p.is_file() and actual == {k:r[k] for k in ('size','mtime_ns','device','inode')} and (not r.get('content_sha256') or content_hash(p)==r['content_sha256']):
                    found.append(rel)
            except (OSError,ValueError) as exc:
                observed.append(dict(path=rel,error=str(exc)))
        # A case-only rename can resolve to two spellings of one file on Windows.
        exact = set()
        for folder in {safe_path(root, s).parent for s in found}:
            if folder not in exact_cache:
                try:exact_cache[folder] = {p.relative_to(root).as_posix() for p in folder.iterdir()}
                except OSError:exact_cache[folder] = set()
            exact.update(exact_cache[folder])
        found = [s for s in found if s in exact]
        states.append(dict(old=r['old'], new=r['new'], temp=r.get('temp'), found=found,observed=observed))
    return states


def process_running(pid):
    if not isinstance(pid,int) or pid <= 0:
        return True
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[ctypes.c_uint32,ctypes.c_int,ctypes.c_uint32];api.OpenProcess.restype=ctypes.c_void_p
    api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32)]
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.OpenProcess(0x1000,0,pid)
    if not handle:return ctypes.get_last_error()!=87  # Access denied is conservatively treated as active.
    try:
        code=ctypes.c_uint32()
        return not api.GetExitCodeProcess(handle,ctypes.byref(code)) or code.value==259
    finally:api.CloseHandle(handle)


@contextmanager
def batch_lock(audit_root, root, batch, recovery=False):
    import hashlib
    lock=audit_root/('directory-'+hashlib.sha256(str(root).casefold().encode()).hexdigest()+'.lock')
    if recovery and lock.exists():
        previous=json.loads(lock.read_text(encoding='utf-8'))
        if previous.get('batch')!=batch or process_running(previous.get('pid')):
            raise ValueError('目录仍被活动批次锁定，或锁属于其他批次；不能执行恢复。')
        move_no_replace(lock,audit_root/('stale-lock-'+uuid.uuid4().hex+'.json'))
    try:
        with lock.open('x',encoding='utf-8') as out:
            json.dump(dict(batch=batch,pid=os.getpid()),out);out.flush();os.fsync(out.fileno())
    except FileExistsError:
        raise ValueError('该目录存在活动或中断的批次锁。请等待任务结束，或通过“恢复失败批次”处理原批次。')
    try:yield
    finally:lock.unlink(missing_ok=True)


def rollback(record, manifest, mover=move_no_replace, progress=None):
    root = Path(record['plan']['root']); rows = record['rows']; errors = []
    report_progress(progress,'rollback_prepare',0,len(rows))
    def save():
        try:write_json(manifest, record)
        except OSError as exc:errors.append(f'写恢复记录失败：{exc}')
    states = locate_states(root, rows)
    record['states'] = states
    # Stage all identifiable displaced files first. Unknown/modified files are never guessed.
    for row, state in zip(rows, states):
        if len(state['found']) != 1:
            row['current']=None
            errors.append(f'无法唯一定位源文件 {state["old"]}：{state["found"]}')
            continue
        current = state['found'][0]
        row['current'] = current
        if current == row['old'] or current == row.get('temp'):
            continue
        try:
            if not matches_row(safe_path(root,current),row):
                raise ValueError('恢复前文件再次变化。')
            mover(safe_path(root,current), safe_path(root,row['temp']))
            row['current'] = row['temp']; save()
        except (OSError,ValueError) as exc:errors.append(f'{current} → {row["temp"]}：{exc}')
    restored_count=sum(row.get('current')==row['old'] for row in rows)
    report_progress(progress,'rollback',restored_count,len(rows))
    for row in rows:
        if row.get('current') == row['old']:
            continue
        if not row.get('current') or row.get('current') != row.get('temp'):
            errors.append(f'未能安全暂存，需人工恢复：{row["old"]}')
            continue
        try:
            if not matches_row(safe_path(root,row['temp']),row):
                raise ValueError('恢复前文件再次变化。')
            mover(safe_path(root,row['temp']), safe_path(root,row['old']))
            row['current'] = row['old']; save()
            restored_count+=1;report_progress(progress,'rollback',restored_count,len(rows),row['old'])
        except (OSError,ValueError) as exc:errors.append(f'{row["temp"]} → {row["old"]}：{exc}')
    record['states'] = locate_states(root, rows)
    record['recovery_errors'] = errors
    restored = all(s['found'] == [s['old']] for s in record['states'])
    record['status'] = 'rolled_back' if restored and not errors else 'recovery_failed'
    save()
    return record


def verify_after(plan, rows):
    root = Path(plan['root'])
    current = inventory(root, plan['recursive'])
    expected = dict(plan['snapshot'])
    for r in rows:expected.pop(r['old'])
    for r in rows:expected[r['new']] = dict(kind='file', **{k:r[k] for k in ('size','mtime_ns','device','inode')})
    if current != expected:
        differences = [p for p in sorted(set(current)|set(expected)) if current.get(p) != expected.get(p)]
        raise ValueError('执行后文件数量、路径或元数据核验失败：'+'；'.join(differences))
    targets = {r['new'] for r in rows}
    for r in rows:
        if r.get('content_sha256') and not matches_row(safe_path(root,r['new']),r):
            raise ValueError('交换后文件内容核验失败：'+r['new'])
        if r['old'] != r['new'] and r['old'] not in targets and r['old'] in current:
            raise ValueError('已更名的旧路径仍存在：'+r['old'])
        if r.get('temp') in current:
            raise ValueError('遗留临时文件：'+r['temp'])
    check = preview(root, plan['prefix'], plan['recursive'])
    if check['issues'] or check['summary']['changes'] or check['summary']['pair_count'] != plan['summary']['pair_count']:
        raise ValueError('执行后 CASE/DAT 配对核验失败：'+json.dumps(check['issues'],ensure_ascii=False))
    return dict(file_count=sum(v['kind']=='file' for v in current.values()), expected_targets=True,
                old_paths_removed=True, metadata_unchanged=True, paired=True, no_temporary_files=True,
                old_path_rule='若旧路径同时是另一文件的最终目标，则核对该目标的文件身份，而非要求路径消失。')


def execute(plan, audit_directory, *, mover=move_no_replace, progress=None):
    """Caller must show the full preview and obtain an explicit Execute click first."""
    # Rebuild instead of trusting an edited mapping, and detect additions/deletions/metadata changes.
    report_progress(progress,'prepare')
    plan = json.loads(json.dumps(plan))
    if plan['issues']:
        raise ValueError('本批次存在问题，已阻止整批执行。')
    root = Path(plan['root']); audit_root = Path(audit_directory).resolve()
    if audit_root.is_relative_to(root):
        raise ValueError('对照清单必须存放在扫描目录之外，避免改变待核验文件数量。')
    assert_unchanged(plan)
    fresh = preview(root, plan['prefix'], plan['recursive'], initial_step=plan.get('initial_step'))
    if fresh['issues'] or fresh['mapping'] != plan['mapping']:
        raise ValueError('预览已失效或映射被更改，请重新扫描。')
    # A persistent exclusive batch lock prevents cooperating instances running on the same root.
    # Parent/child batches are still protected by inventory and no-overwrite checks.
    audit_root.mkdir(parents=True, exist_ok=True)
    manifest = None
    with batch_lock(audit_root,root,plan['batch']):
        batch_dir = audit_root / (datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+plan['batch'])
        batch_dir.mkdir()
        manifest = batch_dir/'batch.json'
        rows = json.loads(json.dumps(plan['mapping']))
        for r in rows:
            r['current'] = r['old']
            r['temp'] = (Path(r['old']).parent/('.fluent-rename-'+uuid.uuid4().hex+'.tmp')).as_posix() if r['old'] != r['new'] else None
        changed = [r for r in rows if r['old'] != r['new']]
        staged=any(os.path.lexists(safe_path(root,r['new'])) for r in changed)
        if staged:
            for r in changed:
                if r['inode']==0:
                    report_progress(progress,'hash',current=r['old'])
                    r['content_sha256']=content_hash(safe_path(root,r['old']))
        report_progress(progress,'record',0,len(changed))
        record = dict(schema=1,status='prepared',plan=plan,rows=rows,manifest=str(manifest),notice=NOTICE)
        write_json(manifest, record)
        data = audit_rows(plan)
        with (batch_dir/'文件名对照.csv').open('x',encoding='utf-8-sig',newline='') as out:
            writer = csv.DictWriter(out,fieldnames=list(data[0]) if data else ['batch','old_path','new_path'])
            writer.writeheader();writer.writerows(data);out.flush();os.fsync(out.fileno())
        changed = [r for r in rows if r['old'] != r['new']]
        try:
            assert_unchanged(plan)
            record['status']='executing';write_json(manifest,record)
            # Only collisions with another source (including case-only renames) need staging.
            staged=any(os.path.lexists(safe_path(root,r['new'])) for r in changed)
            record['strategy']='staged' if staged else 'direct'
            phase='stage' if staged else 'rename'
            report_progress(progress,phase,0,len(changed))
            for index,r in enumerate(changed,1):
                source = safe_path(root,r['old'])
                if not matches_row(source,r):
                    raise ValueError('执行前文件发生变化：'+r['old'])
                destination=r['temp'] if staged else r['new']
                mover(source,safe_path(root,destination))
                r['current']=destination;write_json(manifest,record)
                if not matches_row(safe_path(root,destination),r):
                    raise ValueError('改名后文件元数据发生变化：'+destination)
                report_progress(progress,phase,index,len(changed),r['new'])
            if staged:report_progress(progress,'rename',0,len(changed))
            for index,r in enumerate(changed if staged else [],1):
                if not matches_row(safe_path(root,r['temp']),r):
                    raise ValueError('执行时临时文件发生变化：'+r['temp'])
                mover(safe_path(root,r['temp']),safe_path(root,r['new']))
                r['current']=r['new'];write_json(manifest,record)
                report_progress(progress,'rename',index,len(changed),r['new'])
            report_progress(progress,'verify',len(changed),len(changed))
            record['verification']=verify_after(plan,rows)
            record['status']='verified';record['success']=len(changed)
            record['unchanged']=len(rows)-len(changed);write_json(manifest,record)
        except Exception as exc:
            record['error']=str(exc);record['status']='rolling_back'
            try:write_json(manifest,record)
            except OSError:pass
            record=rollback(record,manifest,mover,progress)
        return record


def recover(manifest_path, *, mover=move_no_replace, progress=None):
    """Explicit recovery from a recorded interrupted/failed batch; never overwrites any file."""
    manifest = Path(manifest_path).resolve()
    record = json.loads(manifest.read_text(encoding='utf-8'))
    if record.get('schema') != 1 or record.get('status') not in ('prepared','executing','rolling_back','recovery_failed'):
        raise ValueError('只允许恢复本工具尚未成功或尚未完全回滚的批次。')
    root=Path(record['plan']['root']).resolve()
    for row in record['rows']:
        for field in ('old','new','temp'):
            if row.get(field):safe_path(root,row[field])
    record['manifest']=str(manifest)
    with batch_lock(manifest.parent.parent,root,record['plan']['batch'],recovery=True):
        return rollback(record,manifest,mover,progress)
