"""Hidden-window motion verification. No mouse/keyboard automation or real CFD input."""
from pathlib import Path
import sys,time,unittest,tempfile
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import app
from motion_widgets import CompletionButton,SlidingSwitch,feedback_frame
import filename_normalizer as engine


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.root=app.App(auto_detect=False);self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
    def tearDown(self):
        for timer in self.root.tk.call('after','info'):
            try:self.root.tk.call('after','cancel',timer)
            except Exception:pass
        self.root.destroy();self.assertEqual(self.errors,[])
    def pump(self,seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:self.root.update();time.sleep(.008)
    def test_geometry_phases(self):
        self.assertEqual(feedback_frame(0,160,36)['width'],160)
        self.assertEqual(feedback_frame(.24,160,36)['width'],36)
        self.assertLess(len(feedback_frame(.35,160,36)['check']),len(feedback_frame(.56,160,36)['check']))
        self.assertEqual(len(feedback_frame(.7,160,36)['particles']),10)
        self.assertFalse(feedback_frame(.5,160,36)['particles'])
        self.assertTrue(feedback_frame(1.28,160,36)['done'])
    def test_close_during_initialization_is_deferred(self):
        self.root._initializing=True;self.root.close()
        self.assertTrue(self.root._close_requested);self.assertTrue(self.root.winfo_exists())
        self.root._initializing=False
    def test_actual_primary_button_named_white_completes(self):
        button=self.root.completion_buttons['convert']
        self.assertEqual(button.cget('text_color'),'white')
        button.success(animate_hidden=True);self.pump(1.4)
        self.assertEqual(button.feedback_stages,['shrink','check','particles','restore'])
        self.assertFalse(button.feedback_running);self.assertIsNone(button._effect_canvas)
    def test_animation_failure_keeps_completed_status_and_polling(self):
        button=self.root.completion_buttons['convert']
        original=button.success
        def fail():raise ValueError('simulated animation failure')
        button.success=fail;self.root.busy=True
        self.root.events.put(('done',(0,'convert')));self.root.poll()
        self.assertFalse(self.root.busy)
        self.assertIn('完成',self.root.status.get())
        self.assertEqual(len(self.errors),1);self.errors.clear();button.success=original
        self.root.events.put(('line','polling still works\n'));self.pump(.2)
        self.assertIn('polling still works',self.root.log.get('1.0','end'))
    def test_animation_runs_and_does_not_change_layout_or_state(self):
        calls=[];b=CompletionButton(self.root,text='完成',width=160,height=36,command=lambda:calls.append('clicked'))
        b.grid(row=9,column=0);b.configure(state='disabled');before=(b.cget('width'),b.cget('height'),b.cget('state'))
        b.success(animate_hidden=True);self.pump(.38)
        self.assertTrue(b.feedback_running);self.assertIsNotNone(b._effect_canvas)
        b.invoke();self.assertEqual(calls,[])
        self.pump(1.05)
        self.assertEqual(b.feedback_stages,['shrink','check','particles','restore'])
        self.assertFalse(b.feedback_running);self.assertIsNone(b._effect_canvas)
        self.assertEqual(before,(b.cget('width'),b.cget('height'),b.cget('state')))
    def test_confirmation_closes_only_after_feedback_once(self):
        calls=[];b=CompletionButton(self.root,text='知道了',command=lambda:calls.append('closed'),confirm=True);b.grid(row=9,column=0)
        b.invoke();self.assertTrue(b.feedback_pending);self.assertFalse(calls)
        b._start_feedback();b.invoke();b.invoke();self.pump(1.4)
        self.assertEqual(calls,['closed']);self.assertEqual(b.feedback_count,1)
    def test_destroy_during_animation_cancels_timer(self):
        b=CompletionButton(self.root,text='完成');b.grid(row=9,column=0);b.success(animate_hidden=True)
        self.pump(.08);b.destroy();self.pump(.1)
        self.assertIsNone(b._effect_canvas);self.assertIsNone(b._effect_timer)
    def test_hidden_fallback_is_confined_to_button(self):
        b=self.root.completion_buttons['convert'];b.success(animate_hidden=True)
        self.assertIs(b._effect_canvas.master,b);self.assertEqual(b._effect_pad,0)
        self.assertIsNone(b._effect_overlay)
    @unittest.skipUnless(sys.platform=='win32','Windows transparent overlay')
    def test_mapped_feedback_has_transparent_nonactivating_layer_and_local_mask(self):
        import ctypes
        self.root.attributes('-alpha',0);self.root.geometry('1120x820+20000+20000');self.root.deiconify();self.root.update()
        b=self.root.completion_buttons['convert'];b.success();self.pump(.1)
        overlay=b._effect_overlay;self.assertIsNotNone(overlay)
        self.assertEqual(str(overlay.attributes('-transparentcolor')),'#FF00FE')
        self.assertEqual(b._effect_canvas.cget('bg'),'#FF00FE')
        self.assertIs(b._effect_mask.master,b)
        self.assertEqual(b._effect_mask.winfo_width(),b.winfo_width())
        self.assertEqual(b._effect_mask.winfo_height(),b.winfo_height())
        user=ctypes.WinDLL('user32');user.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user.GetAncestor.restype=ctypes.c_void_p
        user.GetWindowLongW.argtypes=[ctypes.c_void_p,ctypes.c_int];user.GetWindowLongW.restype=ctypes.c_long
        style=user.GetWindowLongW(user.GetAncestor(overlay.winfo_id(),2),-20)
        self.assertTrue(style&0x08000000);self.assertTrue(style&0x20)
        b.reset_feedback();self.assertIsNone(b._effect_overlay);self.assertIsNone(b._effect_mask)
        self.assertFalse(overlay.winfo_exists())
    @unittest.skipUnless(sys.platform=='win32','Windows transparent overlay')
    def test_transparent_layer_follows_button_and_is_removed_on_unmap(self):
        self.root.attributes('-alpha',0);self.root.geometry('1120x820+20000+20000');self.root.deiconify();self.root.update()
        b=self.root.completion_buttons['convert'];b.success();self.pump(.06)
        self.root.geometry('1120x820+20100+20100');self.pump(.08)
        self.assertEqual(b._effect_overlay.winfo_rootx(),b.winfo_rootx()-b._effect_pad)
        self.root.withdraw();self.pump(.05)
        self.assertFalse(b.feedback_running);self.assertIsNone(b._effect_overlay)
    def test_switch_fast_reversal_and_keyboard_state(self):
        switch=self.root.normalizer.tabs.switch
        switch.set('检查详情');self.pump(.06);switch.set('改名前后');self.pump(.26)
        self.assertEqual(switch.value,'改名前后');self.assertAlmostEqual(switch.position,0)
        switch.set('检查详情');self.pump(.25)
        self.assertEqual(self.root.normalizer.tabs.get(),'检查详情');self.assertAlmostEqual(switch.position,1)
    def test_switch_drag_snaps(self):
        switch=self.root.normalizer.tabs.switch
        switch.canvas.configure(width=244,height=38);switch.canvas.place(width=244,height=38);self.root.update_idletasks()
        switch.press(SimpleNamespace(x=10));switch.drag(SimpleNamespace(x=240));switch.release(SimpleNamespace(x=240));self.pump(.26)
        self.assertEqual(switch.value,'检查详情');self.assertAlmostEqual(switch.position,1)
    def test_card_alignment_and_helper_colors(self):
        p=self.root.normalizer;a,b=p.step_headers
        self.assertEqual(a[0].grid_info()['padx'],b[0].grid_info()['padx'])
        self.assertEqual(a[1].cget('width'),b[1].cget('width'))
        self.assertEqual(a[2].pack_info()['padx'],b[2].pack_info()['padx'])
        self.assertEqual(p.example_label.cget('text_color'),app.C['muted'])
        self.assertEqual(p.scope_label.cget('text_color'),app.C['muted'])
    def test_all_task_buttons_use_shared_feedback(self):
        self.assertEqual(set(self.root.completion_buttons),{'save','environment','scan','convert'})
        for button in self.root.completion_buttons.values():self.assertIsInstance(button,CompletionButton)
        self.assertIsInstance(self.root.normalizer.scan_button,CompletionButton)
        self.assertIsInstance(self.root.normalizer.execute_button,CompletionButton)
    def test_failed_task_does_not_report_success(self):
        self.root.show_log=lambda:None
        b=self.root.completion_buttons['scan'];self.root.events.put(('done',(1,'scan')));self.root.poll()
        self.assertEqual(b.feedback_count,0)
        self.root.events.put(('done',(0,'scan')));self.root.poll();self.assertEqual(b.feedback_count,1)
    def test_problem_preview_and_rollback_do_not_report_success(self):
        with tempfile.TemporaryDirectory(prefix='motion_test_') as tmp:
            base=Path(tmp);root=base/'files';root.mkdir();(root/'a-00100.dat').write_bytes(b'd')
            panel=self.root.normalizer;panel.enabled.set(True)
            bad=engine.preview(root,'test');panel.events.put(('preview',bad,None));panel.poll()
            self.assertEqual(panel.scan_button.feedback_count,0)
            (root/'a.cas').write_bytes(b'c');good=engine.preview(root,'test')
            panel.events.put(('preview',good,None));panel.poll();self.assertEqual(panel.scan_button.feedback_count,1)
            def fail(*args):raise OSError('mock failure')
            rolled=engine.execute(good,base/'audit',mover=fail)
            panel.events.put(('execute',rolled,None));panel.poll()
            self.assertEqual(panel.execute_button.feedback_count,0)

if __name__=='__main__':unittest.main(verbosity=2)
