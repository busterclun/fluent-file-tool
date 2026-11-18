import contextlib
from enum import Enum
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import environment_check as e


class OldVersions(Enum):
    v241 = '24.1.0'
    v242 = '24.2.0'


class NewVersions(Enum):
    v242 = '24.2.0'
    v261 = '26.1.0'


class EnvironmentTests(unittest.TestCase):
    def modules(self, versions):
        ansys=types.ModuleType('ansys');fluent=types.ModuleType('ansys.fluent')
        core=types.ModuleType('ansys.fluent.core');core.__version__='test';core.launch_fluent=MagicMock()
        ansys.fluent=fluent;fluent.core=core
        return {'ansys':ansys,'ansys.fluent':fluent,'ansys.fluent.core':core,
                'numpy':types.SimpleNamespace(__version__='test'),
                'ansys.fluent.core.utils.fluent_version':types.SimpleNamespace(FluentVersion=versions)}

    def test_compatible_and_other_supported_versions_do_not_launch_solver(self):
        for versions, version in ((OldVersions,'24.1.0'),(NewVersions,'24.2.0')):
            modules=self.modules(versions)
            with patch.dict(sys.modules,modules),contextlib.redirect_stdout(io.StringIO()) as output:
                e.check_environment(version)
            modules['ansys.fluent.core'].launch_fluent.assert_not_called()
            self.assertIn('兼容性检查通过',output.getvalue())

    def test_unsupported_version_has_actionable_error(self):
        with patch.dict(sys.modules,self.modules(NewVersions)):
            with self.assertRaisesRegex(ValueError,'不支持 Fluent 24.1.0') as error:
                e.check_environment('24.1.0')
        self.assertIn('0.37.2',str(error.exception));self.assertIn('24.2.0',str(error.exception))

    def test_invalid_version_and_missing_installation(self):
        for version in ('241','2024 R1','24.1','24.1.1'):
            with self.assertRaises(ValueError):e.check_environment(version)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'安装位置'):e.check_environment('24.1.0',tmp)
            root=Path(tmp)/'v242';exe=root/'fluent/ntbin/win64/fluent.exe';exe.parent.mkdir(parents=True);exe.touch()
            with self.assertRaisesRegex(ValueError,'不一致'):e.check_environment('24.1.0',str(root))

    def test_cli_returns_failure_instead_of_success_on_incompatible_or_missing_dependency(self):
        with patch.object(sys,'argv',['check','--version','24.1.0']),patch.dict(sys.modules,self.modules(NewVersions)):
            self.assertEqual(e.main(),1)
        with patch.object(sys,'argv',['check','--version','24.1.0']),patch.dict(sys.modules,{'numpy':None}):
            self.assertEqual(e.main(),1)

    def test_worker_rejects_before_touching_output(self):
        worker_path=Path(e.__file__).with_name('worker.py')
        spec=importlib.util.spec_from_file_location('environment_worker_test',worker_path)
        worker=importlib.util.module_from_spec(spec);converter=MagicMock()
        with patch.dict(sys.modules,{'converter':converter}):spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            with patch.object(sys,'argv',['worker','convert','--input',tmp,'--output',str(out)]),patch.object(worker,'check_environment',side_effect=ValueError('unsupported')):
                with self.assertRaisesRegex(ValueError,'unsupported'):worker.main()
            self.assertFalse(out.exists());converter.main.assert_not_called()

    def test_gui_passes_selected_version_and_root_to_probe(self):
        from app import App
        app=App(auto_detect=False);app.withdraw()
        try:
            cfg={'python':'selected-python','version':'24.1.0','fluent_root':'selected-root'}
            with patch.object(app,'configuration',return_value=cfg),patch.object(app,'validate_environment'),patch.object(app,'start_job') as start:
                app.check_environment()
            cmd,action=start.call_args.args
            self.assertEqual(action,'environment');self.assertEqual(cmd[0],cfg['python'])
            self.assertTrue(cmd[2].endswith('environment_check.py'))
            self.assertEqual(cmd[3:],['--version','24.1.0','--fluent-root','selected-root'])
        finally:
            for timer in app.tk.call('after','info'):app.tk.call('after','cancel',timer)
            app.destroy()


if __name__=='__main__':unittest.main()
