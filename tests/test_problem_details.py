import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from app import App
import filename_normalizer as n

class ProblemDetailsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'a.cas').write_bytes(b'case');(self.root/'a-00010.dat').write_bytes(b'data')
        self.app=App(auto_detect=False);self.app.withdraw();self.panel=self.app.normalizer
        self.plan=n.preview(self.root,'out')
    def tearDown(self):
        for timer in self.app.tk.call('after','info'):self.app.tk.call('after','cancel',timer)
        self.app.destroy();self.temp.cleanup()
    def test_failure_opens_readable_popup_with_reason_first(self):
        result=dict(plan=self.plan,rows=self.plan['mapping'],manifest=str(self.root/'batch.json'),status='recovery_failed',error='[WinError 5] batch.json denied',recovery_errors=['write failed'])
        self.panel.finish_job('execute',result,None)
        self.assertTrue(self.panel.detail_window.winfo_exists())
        text=self.panel.detail_box.get('1.0','end')
        self.assertLess(text.index('batch.json denied'),text.index('完整检查记录'))
        self.assertTrue(self.panel.settings_collapsed)
        self.assertEqual(self.panel.execute_button.feedback_count,0)
    def test_preview_collapses_form_and_can_reopen(self):
        self.app.attributes('-alpha',0);self.app.geometry('1000x720+20000+20000');self.app.deiconify();self.app.show_page('normalize')
        self.panel.show_plan(self.plan);self.panel.tabs.set('检查详情');self.app.update()
        self.assertGreater(self.panel.details.winfo_height(),100)
        self.panel.toggle_settings();self.assertFalse(self.panel.settings_collapsed)
    def test_generic_error_and_manual_reopen(self):
        self.panel.finish_job('execute',None,'unable to save record')
        self.assertIn('unable to save',self.panel.detail_box.get('1.0','end'))
        self.panel.detail_window.destroy();self.panel.open_details()
        self.assertTrue(self.panel.detail_window.winfo_exists())

class StartupCloseTests(unittest.TestCase):
    def test_close_during_titlebar_setup_waits_until_setup_returns(self):
        from unittest.mock import patch
        app=App(auto_detect=False);app._window_exists=False
        states=[]
        def setup(mode):
            app.close();states.append(bool(app.winfo_exists()))
            app.state('withdrawn')
        with patch.object(app,'_windows_set_titlebar_color',side_effect=setup):app.mainloop()
        self.assertEqual(states,[True]);self.assertTrue(app._close_requested)

if __name__=='__main__':unittest.main()
