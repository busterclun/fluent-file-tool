import sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import filename_normalizer as n
from app import App

class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'files';self.root.mkdir();self.audit=self.base/'audit'
        for i in range(2):
            (self.root/f'save{i}.cas').write_bytes(b'case')
            (self.root/f'save{i}-{i+1:05d}.dat').write_bytes(b'data')
    def tearDown(self):self.temp.cleanup()
    def test_counts_emitted_after_each_rename_and_before_verification(self):
        updates=[]
        def progress(event):
            updates.append(event)
            if event['phase']=='rename' and event['done']:
                self.assertTrue((self.root/event['current']).exists())
        result=n.execute(n.preview(self.root,'new'),self.audit,progress=progress)
        self.assertEqual(result['status'],'verified')
        steps=[e['done'] for e in updates if e['phase']=='rename']
        self.assertEqual(steps,[0,1,2,3,4]);self.assertEqual(updates[-1]['phase'],'verify')
    def test_feedback_failure_cannot_break_file_operation(self):
        def broken(event):raise RuntimeError('display unavailable')
        result=n.execute(n.preview(self.root,'new'),self.audit,progress=broken)
        self.assertEqual(result['status'],'verified')
    def test_rollback_reports_restored_file_count(self):
        events=[];calls=0
        def failing(src,dst):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('simulated rename failure')
            n.move_no_replace(src,dst)
        result=n.execute(n.preview(self.root,'new'),self.audit,mover=failing,progress=events.append)
        self.assertEqual(result['status'],'rolled_back')
        restored=[e for e in events if e['phase']=='rollback']
        self.assertTrue(restored);self.assertEqual(restored[-1]['done'],4)
    def test_ui_progress_keeps_task_busy_until_verified_result(self):
        app=App(auto_detect=False);app.withdraw();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            panel=app.normalizer;panel.enabled.set(True)
            def slow_move(src,dst):time.sleep(.13);n.move_no_replace(src,dst)
            plan=n.preview(self.root,'new')
            panel.run_job('execute',lambda:n.execute(plan,self.audit,mover=slow_move,progress=panel.enqueue_progress))
            deadline=time.monotonic()+8;observed=False
            while panel.running and time.monotonic()<deadline:
                app.update();time.sleep(.005)
                if panel._progress_phase=='rename' and 0<panel.task_progress.get()<1:
                    observed=True;self.assertTrue(app.busy);self.assertEqual(panel.execute_button.cget('state'),'disabled')
            self.assertTrue(observed);self.assertFalse(panel.running);self.assertFalse(app.busy)
            self.assertEqual(panel.task_progress.get(),1);self.assertIn('已改名 4 个',panel.progress_text.get());self.assertFalse(errors)
        finally:
            for timer in app.tk.call('after','info'):app.tk.call('after','cancel',timer)
            app.destroy()
    def test_verify_does_not_show_completed_and_failure_stops_animation(self):
        app=App(auto_detect=False);app.withdraw()
        try:
            p=app.normalizer;p.running=True;app.busy=True
            p.events.put(('progress',dict(phase='verify',done=4,total=4,current=''),None));p.poll()
            self.assertTrue(p.running);self.assertTrue(app.busy);self.assertLess(p.task_progress.get(),1)
            p.events.put(('execute',None,'simulated error'));p.poll()
            self.assertFalse(p.running);self.assertLess(p.task_progress.get(),1);self.assertIn('已停止',p.progress_text.get())
            self.assertEqual(p.execute_button.feedback_count,0)
        finally:
            for timer in app.tk.call('after','info'):app.tk.call('after','cancel',timer)
            app.destroy()

    def test_initial_controls_invalidate_preview_and_pass_confirmed_number(self):
        app=App(auto_detect=False);app.withdraw()
        try:
            p=app.normalizer;p.enabled.set(True);p.directory.set(str(self.root));p.sync()
            self.assertFalse(p.include_initial.get());self.assertEqual(p.initial_entry.cget('state'),'disabled')
            captured=[];p.run_job=lambda kind,call:captured.append(call())
            p.scan();self.assertIsNone(captured[-1]['initial_step'])
            p.plan=captured[-1];p.initial_toggle.toggle()
            self.assertIsNone(p.plan);self.assertEqual(p.initial_entry.cget('state'),'normal')
            p.scan();self.assertEqual(captured[-1]['initial_step'],'0')
            p.plan=captured[-1];p.initial_step.set('5');self.assertIsNone(p.plan)
            p.scan();self.assertEqual(captured[-1]['initial_step'],'5')
            app.busy=True;p.sync()
            self.assertEqual(p.initial_toggle.cget('state'),'disabled');self.assertEqual(p.initial_entry.cget('state'),'disabled')
        finally:
            for timer in app.tk.call('after','info'):app.tk.call('after','cancel',timer)
            app.destroy()

if __name__=='__main__':unittest.main()
