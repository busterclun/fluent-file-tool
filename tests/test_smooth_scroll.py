"""Synthetic wheel input in hidden windows; never controls the user's pointer."""
import sys,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import customtkinter as ctk
from smooth_scroll import SmoothScrollableFrame,wheel_pixels


class ScrollTests(unittest.TestCase):
    def setUp(self):
        self.root=ctk.CTk();self.root.withdraw();self.errors=[]
        self.root.report_callback_exception=lambda *args:self.errors.append(args)
        self.frame=SmoothScrollableFrame(self.root);self.frame.pack()
        self.label=ctk.CTkLabel(self.frame,text='测试内容');self.label.pack()
        self.root.update_idletasks();self.canvas=self.frame._parent_canvas
        self.canvas.configure(scrollregion=(0,0,600,3000));self.canvas.winfo_height=lambda:300
        self.canvas.yview_moveto(0)
    def tearDown(self):
        for timer in self.root.tk.call('after','info'):self.root.tk.call('after','cancel',timer)
        self.root.destroy();self.assertEqual(self.errors,[])
    def pump(self,seconds=.28):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:self.root.update();time.sleep(.006)
    def pos(self):return self.canvas.yview()[0]*3000
    def event(self,delta,widget=None):return SimpleNamespace(delta=delta,widget=widget or self.label,num=None)
    def test_normal_notch_and_dpi(self):
        self.assertEqual(wheel_pixels(-120,1,'win32'),84)
        self.assertEqual(wheel_pixels(-120,1.5,'win32'),126)
        self.frame._mouse_wheel_all(self.event(-120));self.assertGreater(self.pos(),0)
        self.pump();self.assertAlmostEqual(self.pos(),84*self.frame._get_widget_scaling(),delta=1)
    def test_notch_starts_immediately_without_full_jump(self):
        self.frame.scroll_pixels(84)
        self.assertGreater(self.pos(),0);self.assertLess(self.pos(),25)
        self.assertIsNotNone(self.frame._scroll_timer)
    def test_no_motion_after_short_transition(self):
        self.frame.scroll_pixels(84);self.pump(.1);before=self.pos();self.pump(.2)
        self.assertEqual(self.pos(),before)
        self.assertIsNone(self.frame._scroll_timer)
    def test_linear_motion_has_fixed_deadline(self):
        with patch('smooth_scroll.time.monotonic',return_value=10.) as clock:
            self.frame.scroll_pixels(84)
            for elapsed in (.016,.032,.044,.0521):
                clock.return_value=10.+elapsed;self.frame._advance_scroll()
                self.assertAlmostEqual(self.pos(),84*min(1,(elapsed+.008)/.060),delta=1)
            self.assertEqual(self.frame._segments,[]);self.assertIsNone(self.frame._scroll_timer)
    def test_new_input_does_not_extend_earlier_deadline(self):
        with patch('smooth_scroll.time.monotonic',return_value=10.) as clock:
            self.frame.scroll_pixels(84)
            clock.return_value=10.020;self.frame.scroll_pixels(84)
            clock.return_value=10.0521;self.frame._advance_scroll()
            self.assertEqual(len(self.frame._segments),1)
            self.assertAlmostEqual(self.pos(),84+84*(.0401/.060),delta=1)
            clock.return_value=10.0721;self.frame._advance_scroll()
            self.assertAlmostEqual(self.pos(),168,delta=1);self.assertIsNone(self.frame._scroll_timer)
    def test_late_frame_finishes_without_replaying_animation(self):
        with patch('smooth_scroll.time.monotonic',return_value=10.) as clock:
            self.frame.scroll_pixels(84)
            clock.return_value=10.5;self.frame._advance_scroll()
            self.assertAlmostEqual(self.pos(),84,delta=1);self.assertIsNone(self.frame._scroll_timer)
    def test_precision_wheel_is_direct_without_timer(self):
        for _ in range(12):self.frame._mouse_wheel_all(self.event(-1))
        self.assertAlmostEqual(self.pos(),12*.7*self.frame._get_widget_scaling(),delta=1)
        self.assertIsNone(self.frame._scroll_timer)
    def test_position_only_configure_does_not_recompute_region(self):
        writes=[];original=self.canvas.configure
        def configure(*args,**kwargs):
            if 'scrollregion' in kwargs:writes.append(kwargs['scrollregion'])
            return original(*args,**kwargs)
        self.canvas.configure=configure
        self.frame._content_size=(600,3000)
        for _ in range(20):self.frame._update_scroll_region(SimpleNamespace(width=600,height=3000))
        self.assertEqual(writes,[])
        self.frame._update_scroll_region(SimpleNamespace(width=600,height=3100))
        self.assertEqual(len(writes),1)
    def test_external_scroll_resynchronizes_position(self):
        self.frame.scroll_pixels(84);self.canvas.yview_moveto(.4)
        before=self.pos();self.frame.scroll_pixels(84)
        self.pump(.1)
        self.assertAlmostEqual(self.pos(),before+84,delta=1)
    def test_partial_notches_not_lost(self):
        for _ in range(24):self.frame._mouse_wheel_all(self.event(-1))
        self.pump();self.assertAlmostEqual(self.pos(),24*.7*self.frame._get_widget_scaling(),delta=1)
    def test_reversal_discards_pending_direction(self):
        self.frame.scroll_pixels(500);before=self.pos()
        self.frame.scroll_pixels(-84);self.assertLess(self.pos(),before);self.pump()
        self.assertLess(self.pos(),before);self.assertAlmostEqual(self.pos(),max(0,before-84),delta=1)
    def test_fast_wheel_accumulates(self):
        for _ in range(4):self.frame.scroll_pixels(84)
        self.pump();self.assertAlmostEqual(self.pos(),336,delta=1)
    def test_limits_no_overshoot(self):
        self.frame.scroll_pixels(100000);self.pump(.4);self.assertAlmostEqual(self.pos(),2700,delta=1)
        self.frame.scroll_pixels(-100000);self.pump(.4);self.assertAlmostEqual(self.pos(),0,delta=1)
    def test_short_content_not_scrolled(self):
        self.canvas.configure(scrollregion=(0,0,600,200));self.frame.scroll_pixels(84)
        self.assertIsNone(self.frame._scroll_timer)
    def test_foreign_page_untouched(self):
        foreign=ctk.CTkLabel(self.root,text='other')
        self.assertIsNone(self.frame._mouse_wheel_all(self.event(-120,foreign)))
        self.assertEqual(self.pos(),0)
    def test_scrollbar_wheel_same_response(self):
        self.frame._scrollbar_wheel(self.event(-120));self.pump()
        self.assertAlmostEqual(self.pos(),84*self.frame._get_widget_scaling(),delta=1)
    def test_cancel_stops_pending_motion(self):
        self.frame.scroll_pixels(500);self.frame.cancel_scroll();before=self.pos();self.pump()
        self.assertEqual(self.pos(),before);self.assertIsNone(self.frame._scroll_timer)
    def test_destroy_only_removes_own_global_bindings(self):
        other=SmoothScrollableFrame(self.root);other.pack()
        mine=[identity for sequence,identity in self.frame._owned_bindings if sequence=='<MouseWheel>']
        theirs=[identity for sequence,identity in other._owned_bindings if sequence=='<MouseWheel>']
        self.frame.scroll_pixels(500);self.frame.destroy()
        script=self.root.bind_all('<MouseWheel>')
        self.assertTrue(all(i not in script for i in mine))
        self.assertTrue(all(i in script for i in theirs));self.pump(.1)

if __name__=='__main__':unittest.main(verbosity=2)
