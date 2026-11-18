import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import environment_discovery as d
from app import App


class DiscoveryTests(unittest.TestCase):
    def test_paths_include_registered_installation_and_sibling_venvs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fluent=root/'v241';exe=fluent/'fluent/ntbin/win64/fluent.exe'
            exe.parent.mkdir(parents=True);exe.touch()
            interpreters=[root/name/'Scripts/python.exe' for name in ('.venv','.venv241')]
            for p in interpreters:p.parent.mkdir(parents=True);p.touch()
            cfg=dict(fluent_root=str(fluent),version='24.1.0',python=str(interpreters[0]))
            with patch.object(d,'registry_paths',return_value=([],[root])):
                installs,candidates=d.discover_paths(cfg,root)
            self.assertIn(dict(fluent_root=str(fluent),version='24.1.0'),installs)
            self.assertTrue(set(interpreters)<=set(candidates));self.assertLessEqual(len(candidates),32)

    def options(self,config):
        installs=[dict(fluent_root='C:/ANSYS/v241',version='24.1.0'),dict(fluent_root='C:/ANSYS/v242',version='24.2.0')]
        def probe(path,*args):
            return dict(executable=str(path),python='3.13',pyfluent='old' if path=='old' else 'new',
                        supported=['24.1.0','24.2.0'] if path=='old' else ['24.2.0'])
        with patch.object(d,'discover_paths',return_value=(installs,['old','new'])),patch.object(d,'probe_python',side_effect=probe):
            return d.detect(config,'.','probe')

    def test_incompatible_environment_is_excluded_and_saved_compatible_preferred(self):
        cfg=dict(fluent_root='C:/ANSYS/v241',version='24.1.0',python='new')
        result=self.options(cfg)
        self.assertEqual(result['options'][0]['python'],'old')
        self.assertFalse(any(i['python']=='new' and i['version']=='24.1.0' for i in result['options']))
        cfg.update(fluent_root='C:/ANSYS/v242',version='24.2.0')
        self.assertEqual(self.options(cfg)['options'][0]['python'],'new')

    def test_no_installation_does_not_probe_python(self):
        with patch.object(d,'discover_paths',return_value=([],['py'])),patch.object(d,'probe_python') as probe:
            result=d.detect({},'.','probe')
        probe.assert_not_called();self.assertFalse(result['options']);self.assertIn('手动选择',result['reason'])

    def test_missing_dependencies_returns_no_compatible_pair(self):
        with patch.object(d,'discover_paths',return_value=([dict(fluent_root='v241',version='24.1.0')],['py'])),patch.object(d,'probe_python',return_value=None):
            result=d.detect({},'.','probe')
        self.assertFalse(result['options']);self.assertIn('Python',result['reason'])

    def test_probe_parses_json_and_ignores_failed_interpreter(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'probe.py'
            script.write_text('import json; print("notice"); print(json.dumps(dict(python="3",pyfluent="test",supported=["24.1.0"])))')
            self.assertEqual(d.probe_python(sys.executable,script)['supported'],['24.1.0'])
            script.write_text('raise SystemExit(1)')
            self.assertIsNone(d.probe_python(sys.executable,script))

    def test_closing_cancels_running_probe_promptly(self):
        with tempfile.TemporaryDirectory() as tmp:
            script=Path(tmp)/'probe.py';script.write_text('import time;time.sleep(60)')
            cancel=threading.Event();timer=threading.Timer(.2,cancel.set);timer.start();start=time.monotonic()
            try:self.assertIsNone(d.probe_python(sys.executable,script,cancel))
            finally:timer.cancel()
            self.assertLess(time.monotonic()-start,3)


class DiscoveryUITests(unittest.TestCase):
    def setUp(self):
        self.app=App(auto_detect=False);self.app.withdraw()
        self.item=dict(fluent_root='E:/ANSYS/v241',version='24.1.0',python='E:/env/python.exe',pyfluent='0.37.2',python_version='3.13')
    def tearDown(self):
        self.app.detect_cancel.set()
        for timer in self.app.tk.call('after','info'):self.app.tk.call('after','cancel',timer)
        self.app.destroy()
    def snapshot(self):return tuple(self.app.vars[k].get().strip() for k in d.ENV_KEYS)
    def test_result_fills_all_three_fields_and_can_select_alternative(self):
        other=dict(self.item,python='E:/other/python.exe')
        self.app.apply_detection(self.snapshot(),dict(options=[self.item,other]))
        self.assertEqual(self.snapshot(),tuple(self.item[k] for k in d.ENV_KEYS))
        self.app.select_detected_environment(list(self.app.detect_options)[1])
        self.assertEqual(self.app.vars['python'].get(),other['python'])
    def test_manual_edit_during_scan_is_not_overwritten(self):
        snapshot=self.snapshot();self.app.vars['python'].set('my-choice')
        self.app.apply_detection(snapshot,dict(options=[self.item]))
        self.assertEqual(self.app.vars['python'].get(),'my-choice')
        self.assertIn('保留你的输入',self.app.detection_status.get())
    def test_no_result_preserves_manual_settings(self):
        snapshot=self.snapshot();self.app.apply_detection(snapshot,dict(options=[],reason='not found'))
        self.assertEqual(snapshot,self.snapshot());self.assertEqual(self.app.detect_choice.cget('state'),'disabled')
    def test_result_waits_until_active_job_finishes(self):
        snapshot=self.snapshot();self.app.busy=True
        self.app.events.put(('environment_detected',(snapshot,dict(options=[self.item]))));self.app.poll()
        self.assertEqual(snapshot,self.snapshot());self.assertIsNotNone(self.app.pending_detection)
        self.app.busy=False;self.app.poll();self.assertIsNone(self.app.pending_detection)
        self.assertEqual(self.app.vars['python'].get(),self.item['python'])
    def test_worker_detects_in_background_and_delivers_to_ui(self):
        with patch.object(d,'detect',return_value=dict(options=[self.item])) as detector:
            self.app.detect_environment();deadline=time.monotonic()+2
            while self.app.detecting and time.monotonic()<deadline:
                self.app.update();time.sleep(.01)
            detector.assert_called_once()
        self.assertFalse(self.app.detecting);self.assertEqual(self.app.vars['python'].get(),self.item['python'])
    def test_startup_schedules_automatic_detection(self):
        with patch.object(App,'detect_environment') as detect:
            other=App();other.withdraw()
            try:
                deadline=time.monotonic()+.65
                while time.monotonic()<deadline:other.update();time.sleep(.01)
                detect.assert_called_once()
            finally:
                for timer in other.tk.call('after','info'):other.tk.call('after','cancel',timer)
                other.destroy()


if __name__=='__main__':unittest.main()
