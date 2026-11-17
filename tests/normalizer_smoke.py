"""Hidden UI integration check: temporary synthetic files only, no Fluent or desktop input."""
import json
from pathlib import Path
import tempfile
import time


def run(window,report_path):
    temp=tempfile.TemporaryDirectory(prefix='fluent_normalizer_ui_')
    root=Path(temp.name)/'中文 目录';root.mkdir()
    cas=root/'save.cas';dat=root/'save-02500.dat'
    cas.write_bytes(b'mock-case');dat.write_bytes(b'mock-data')
    panel=window.normalizer;panel.audit_directory=Path(temp.name)/'audit'
    outcomes=[];deadline=time.monotonic()+30
    window.smoke_failure=False

    def finish(error=None):
        window.smoke_failure=error is not None
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(dict(ok=not error,checks=outcomes,error=str(error) if error else None),ensure_ascii=False,indent=2),encoding='utf-8')
        temp.cleanup();window.destroy()

    def guarded(call):
        try:call()
        except Exception as exc:finish(exc)

    def wait_then(call):
        if time.monotonic()>deadline:finish(TimeoutError('UI task timeout'));return
        if window.busy:window.after(80,lambda:wait_then(call))
        else:guarded(call)

    def after_execute():
        assert panel.last_manifest
        record=json.loads(Path(panel.last_manifest).read_text(encoding='utf-8'))
        assert record['status']=='verified'
        assert (root/'fuxian_fadhl-02500.cas').read_bytes()==b'mock-case'
        assert (root/'fuxian_fadhl-02500.dat').read_bytes()==b'mock-data'
        assert not cas.exists() and not dat.exists()
        assert panel.execute_button.cget('state')=='disabled'
        outcomes.append('执行按钮完成真实文件系统重命名、展示对照清单，并使旧预览失效')
        panel.scan_button.invoke();window.after(80,lambda:wait_then(after_rescan))

    def after_rescan():
        assert panel.plan['summary']['unchanged']==2
        outcomes.append('重复扫描显示 2 个无需修改')
        panel.enabled.set(False);panel.invalidate()
        assert panel.execute_button.cget('state')=='disabled'
        outcomes.append('关闭开关后禁止执行')
        panel.scan_button.success(animate_hidden=True)
        panel.tabs.set('检查详情')
        window.after(40,lambda:panel.tabs.set('改名前后'))
        window.after(1450,lambda:guarded(after_motion))

    def after_motion():
        assert panel.scan_button.feedback_stages==['shrink','check','particles','restore']
        assert not panel.scan_button.feedback_running and panel.scan_button._effect_canvas is None
        assert panel.scan_button.cget('state')=='disabled'
        outcomes.append('完成动画经过四个阶段，结束后清理图层并保留禁用状态')
        assert panel.tabs.get()=='改名前后' and abs(panel.tabs.switch.position)<.001
        outcomes.append('胶囊切换快速反向操作后正确吸附并显示对应内容')
        finish()

    def after_good_preview():
        assert not panel.plan['issues'];assert panel.execute_button.cget('state')=='normal'
        assert len(panel.table.get_children())==2
        first=panel.table.get_children()[0]
        assert panel.table.heading('old')['text']=='现在的文件名'
        assert panel.table.heading('new')['text']=='改名后的文件名'
        assert panel.table.set(first,'folder')=='所选文件夹'
        assert '/' not in panel.table.set(first,'old') and '\\' not in panel.table.set(first,'old')
        outcomes.append('表格用直白名称展示改名前后，所在文件夹单列')
        assert cas.exists() and dat.exists()  # Scanning is read-only.
        outcomes.append('有效预览显示两条映射，扫描没有更名')
        panel.prefix.set('changed')
        assert panel.execute_button.cget('state')=='disabled' and panel.plan is None
        outcomes.append('修改输入后旧预览立即失效')
        panel.prefix.set('fuxian_fadhl');panel.scan_button.invoke()
        window.after(80,lambda:wait_then(execute))

    def execute():
        assert panel.execute_button.cget('state')=='normal'
        panel.execute_button.invoke();window.after(80,lambda:wait_then(after_execute))

    def after_bad_preview():
        assert panel.plan['issues'] and panel.execute_button.cget('state')=='disabled'
        outcomes.append('问题批次禁止执行')
        panel.prefix.set('fuxian_fadhl');panel.scan_button.invoke()
        window.after(80,lambda:wait_then(after_good_preview))

    def start():
        assert not panel.enabled.get() and not panel.recursive.get()
        assert panel.scan_button.cget('state')=='disabled' and panel.execute_button.cget('state')=='disabled'
        outcomes.append('功能和递归默认关闭')
        window.show_page('normalize');assert window.active_page=='normalize'
        panel.enabled.set(True);panel.invalidate();panel.directory.set(str(root))
        assert '不会处理' in panel.scope_hint.get()
        panel.recursive.set(True);panel.invalidate()
        assert '各层文件夹' in panel.scope_hint.get()
        panel.recursive.set(False);panel.invalidate()
        outcomes.append('两种处理范围有对应解释，切换后原预览失效')
        assert panel.prefix.get()==root.name
        panel.prefix.set('custom');panel.directory.set(str(root))
        assert panel.prefix.get()=='custom'
        outcomes.append('默认前缀来自目录，手动前缀得到保留')
        panel.prefix.set('bad/name');panel.scan_button.invoke()
        window.after(80,lambda:wait_then(after_bad_preview))

    window.after(100,lambda:guarded(start))
