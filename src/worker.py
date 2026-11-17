"""Application backend; invoked by the desktop GUI using the configured PyFluent Python."""
import argparse, csv, json, os, re, sys, time
from pathlib import Path
from datetime import datetime
import converter


def organize(out, prefix, digits):
    report_path = out / 'conversion_report.json'
    report = json.loads(report_path.read_text(encoding='utf-8'))
    if report['status'] != 'complete':
        raise ValueError('转换尚未完成，请先继续转换。')
    ledger_path = out / 'rename_manifest.json'
    plan = []
    if ledger_path.exists():
        previous = json.loads(ledger_path.read_text(encoding='utf-8'))
        if previous['status'] == 'moving':
            if previous['prefix'] != prefix or previous['digits'] != digits:
                raise ValueError('存在未完成的整理，请使用上次的前缀和编号位数继续。')
            plan = previous['files']
    if not plan:
        series, last_step = 1, None
        for job in report['jobs']:
            step = int(job['mesh_and_time']['time'][1])
            if job['data_source']:
                if last_step is not None and step <= last_step:
                    series += 1
                last_step = step
                new_stem = f'series_{series:02d}/{prefix}-{step:0{digits}d}'
            else:
                # Separate case-only files retain their identities without inventing steps.
                new_stem = f'case_only/{job["stem"]}/{prefix}'
            for old, digest in job['output_sha256'].items():
                plan.append(dict(old=old, new=new_stem+Path(old).suffix, sha256=digest,
                                 job=job['stem'], step=step))
    if len({x['new'].casefold() for x in plan}) != len(plan):
        raise ValueError('目标文件名重复，整理已停止。')
    for row in plan:
        old, new = out / row['old'], out / row['new']
        old.resolve().relative_to(out.resolve()); new.resolve().relative_to(out.resolve())
        if old != new and old.exists() and new.exists():
            raise FileExistsError(f'目标文件已存在：{new}')
        candidate = old if old.exists() else new
        if converter.sha256(candidate) != row['sha256']:
            raise ValueError(f'文件内容校验失败：{candidate}')
    backup = out / '_logs' / ('before_naming_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    backup.mkdir(parents=True)
    (backup/'conversion_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    ledger = dict(status='moving',prefix=prefix,digits=digits,files=plan)
    converter.save_report(ledger_path,ledger)
    for row in plan:
        old,new=out/row['old'],out/row['new']
        if old != new and old.exists():
            new.parent.mkdir(parents=True,exist_ok=True)
            old.rename(new)
    for row in plan:
        if converter.sha256(out/row['new']) != row['sha256']:
            raise ValueError('整理后校验失败：'+row['new'])
    mapping = {x['old']:x['new'] for x in plan}
    for job in report['jobs']:
        for field in ['output_sha256','output_bytes']:
            job[field]={mapping.get(k,k):v for k,v in job[field].items()}
        cas=next(k for k in job['output_sha256'] if k.endswith('.cas'))
        job['output_stem']=Path(cas).stem
        job['output_subdirectory']=Path(cas).parent.as_posix()
    report['naming']=dict(prefix=prefix,digits=digits,layout='folders',manifest='rename_manifest.json')
    converter.save_report(report_path,report)
    ledger['status']='verified'
    converter.save_report(ledger_path,ledger)
    with (out/'文件名对照.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['old','new','sha256','job','step']);w.writeheader();w.writerows(plan)
    print(f'整理完成：{len(plan)} 个文件，全部 SHA256 校验通过。',flush=True)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['scan','convert','organize'])
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--prefix',default='fuxian_fadhl')
    p.add_argument('--digits',type=int,default=5)
    p.add_argument('--dimension',type=int,choices=[2,3],default=2)
    p.add_argument('--version',default='24.1.0')
    p.add_argument('--fluent-root',default='')
    p.add_argument('--stop-file',type=Path)
    a=p.parse_args()
    if not re.fullmatch(r'[\w\-. ]+',a.prefix) or a.prefix[-1:] in [' ','.'] or a.prefix in ['.','..']:
        raise ValueError('前缀请使用中英文、数字、空格、下划线或短横线，末尾不能是空格或句点。')
    if not 1 <= a.digits <= 12: raise ValueError('编号位数需为 1—12。')
    if a.fluent_root:
        version=re.fullmatch(r'(\d{2})\.(\d)\.\d',a.version)
        if not version: raise ValueError('版本号格式应为 24.1.0。')
        executable=Path(a.fluent_root)/'fluent/ntbin/win64/fluent.exe'
        if not executable.exists(): raise ValueError('Fluent 安装目录应指向 v241 这一级。')
        os.environ['AWP_ROOT'+version[1]+version[2]]=a.fluent_root
    a.output=a.output.resolve()
    if a.action=='scan':
        jobs=converter.discover(a.input.resolve())
        print(f'发现 {len(jobs)} 项：{sum(d is not None for c,d,s in jobs)} 组 case/data，{sum(d is None for c,d,s in jobs)} 个独立 case。')
        for c,d,s in jobs: print(c.name+' + '+(d.name if d else '[仅 case]'))
        print('时间步以 Fluent 读入后的实际值为准；重置或重复编号自动分组。')
        return 0
    a.output.mkdir(parents=True,exist_ok=True)
    lock=a.output/'.application.lock'
    try:
        with lock.open('x',encoding='utf-8') as f: f.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError('此输出目录已有任务锁。若上次异常退出，请确认相关任务已关闭后删除 .application.lock。')
    try:
        if a.action=='convert':
            # Recover a previously interrupted naming transaction before conversion resume.
            ledger=a.output/'rename_manifest.json'
            if ledger.exists() and json.loads(ledger.read_text(encoding='utf-8'))['status']=='moving':
                organize(a.output,a.prefix,a.digits)
            sys.argv=['converter','--input',str(a.input),'--output',str(a.output),
                      '--version',a.version,'--dimension',str(a.dimension),'--resume']
            if a.stop_file: sys.argv += ['--stop-file',str(a.stop_file)]
            rc=converter.main()
            if rc: return rc
        organize(a.output,a.prefix,a.digits)
        (a.output/'打开结果.txt').write_text('在 Fluent 中选择 File > Read > Case & Data，进入 series_XX 文件夹打开 .cas，同名 .dat 自动配对。\ncase_only 保存无配套 data 的 case。\n详细验证记录见 conversion_report.json；新旧文件名见 文件名对照.csv。\n',encoding='utf-8')
        return 0
    finally:
        lock.unlink(missing_ok=True)

if __name__=='__main__':
    try: sys.exit(main())
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('任务失败：'+str(e),flush=True)
        sys.exit(1)
