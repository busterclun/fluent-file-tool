"""Application backend; invoked by the desktop GUI using the configured PyFluent Python."""
import argparse, csv, json, os, re, sys, time
from pathlib import Path
from datetime import datetime
import converter
from environment_check import check_environment


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['scan','convert'])
    p.add_argument('--input',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--prefix',default='fuxian_fadhl')
    p.add_argument('--digits',type=int,default=5)
    p.add_argument('--dimension',type=int,choices=[2,3],default=2)
    p.add_argument('--version',default='24.1.0')
    p.add_argument('--fluent-root',default='')
    p.add_argument('--stop-file',type=Path)
    a=p.parse_args()
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
        print('转换仅去掉末尾 .h5，保留各自原文件名；共享 CASE 的多组结果分目录保存，避免覆盖。')
        return 0
    # Reject unsupported client/solver combinations before creating output or locks.
    check_environment(a.version, a.fluent_root)
    a.output.mkdir(parents=True,exist_ok=True)
    lock=a.output/'.application.lock'
    try:
        with lock.open('x',encoding='utf-8') as f: f.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError('此输出目录已有任务锁。若上次异常退出，请确认相关任务已关闭后删除 .application.lock。')
    try:
        if a.action=='convert':
            sys.argv=['converter','--input',str(a.input),'--output',str(a.output),
                      '--version',a.version,'--dimension',str(a.dimension),'--resume']
            if a.stop_file: sys.argv += ['--stop-file',str(a.stop_file)]
            rc=converter.main()
            if rc: return rc
        (a.output/'打开结果.txt').write_text('转换已完成：保留源文件名，只移除末尾 .h5。\nCASE 和 DAT 主名不同时请在 Fluent 中分别读取对应文件，配对关系见 conversion_report.json。\n如需统一命名，请使用“整理文件名”页面预览后执行。\n',encoding='utf-8')
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
