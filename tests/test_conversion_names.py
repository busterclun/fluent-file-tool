"""Fake Fluent I/O exercises the full output and resume path using tiny files."""
import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
spec=importlib.util.spec_from_file_location('tested_converter',Path(__file__).resolve().parents[1]/'src'/'converter.py')
c=importlib.util.module_from_spec(spec)
with patch.dict(sys.modules,{k:MagicMock() for k in ['numpy','ansys','ansys.fluent','ansys.fluent.core']}):spec.loader.exec_module(c)

class ConversionNameTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.inputs=self.root/'中文 输入';self.inputs.mkdir();self.output=self.root/'结果'
        self.session=MagicMock()
        def write(path):Path(path).write_bytes(b'(legacy test fixture)'+b'x'*200)
        self.session.tui.file.write_case.side_effect=write
        self.session.tui.file.write_data.side_effect=write
    def tearDown(self):self.temp.cleanup()
    def put(self,name):
        (self.inputs/name).write_bytes(c.HDF5_MAGIC+b'fixture')
    def run_conversion(self):
        with patch.object(sys,'argv',['convert','--input',str(self.inputs),'--output',str(self.output),'--resume']),patch.object(c.pyfluent,'launch_fluent',return_value=self.session),patch.object(c,'snapshot',return_value=({'time':[0,12029]},{})),patch.object(c,'compare',return_value={}),patch.object(c,'array_summary',return_value={}):
            return c.main()
    def test_same_stem_kept_without_time_prefix(self):
        self.put('case2_VOF.cas.h5');self.put('case2_VOF.dat.h5');self.run_conversion()
        self.assertTrue((self.output/'case2_VOF.cas').exists());self.assertTrue((self.output/'case2_VOF.dat').exists())
        self.assertFalse((self.output/'series_01').exists())
    def test_consecutive_jobs_never_reuse_fluent_output_paths(self):
        for i in (1,2,3):self.put(f'case-{i}.cas.h5');self.put(f'case-{i}-{i:05d}.dat.h5')
        paths=[]
        def no_overwrite(path):
            paths.append(str(path))
            if Path(path).exists():return  # Reproduce Fluent declining an overwrite.
            Path(path).write_bytes(b'(unique group '+str(len(paths)).encode()+b')'+b'x'*200)
        self.session.tui.file.write_case.side_effect=no_overwrite
        self.session.tui.file.write_data.side_effect=no_overwrite
        self.run_conversion()
        self.assertEqual(len(paths),6);self.assertEqual(len(set(paths)),6)
        self.assertEqual(len({(self.output/f'case-{i}.cas').read_bytes() for i in (1,2,3)}),3)
    def test_distinct_case_and_data_names_preserved(self):
        self.put('original-36.cas.h5');self.put('original-36-02400.dat.h5');self.run_conversion()
        self.assertTrue((self.output/'original-36.cas').exists());self.assertTrue((self.output/'original-36-02400.dat').exists())
    def test_shared_case_separate_folders_keep_both_original_names(self):
        self.put('model.cas.h5')
        for step in ['00100','00200']:self.put('model-'+step+'.dat.h5')
        self.run_conversion()
        for step in ['00100','00200']:
            folder=self.output/('model-'+step)
            self.assertTrue((folder/'model.cas').exists());self.assertTrue((folder/('model-'+step+'.dat')).exists())
    def test_resume_skips_preserved_names(self):
        self.put('model.cas.h5');self.put('model.dat.h5');self.run_conversion();self.session.reset_mock()
        self.run_conversion();self.session.tui.file.write_case.assert_not_called()
    def test_old_renamed_report_is_rejected(self):
        self.put('model.cas.h5');self.output.mkdir();(self.output/'conversion_report.json').write_text('{"jobs":[]}')
        with self.assertRaisesRegex(ValueError,'旧版'):self.run_conversion()
    def test_existing_target_not_overwritten(self):
        self.put('model.cas.h5');self.output.mkdir();target=self.output/'model.cas';target.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):self.run_conversion()
        self.assertEqual(target.read_bytes(),b'keep')
    def test_source_unchanged_and_report_uses_original_names(self):
        self.put('model.cas.h5');before=(self.inputs/'model.cas.h5').read_bytes();self.run_conversion()
        self.assertEqual((self.inputs/'model.cas.h5').read_bytes(),before)
        report=json.loads((self.output/'conversion_report.json').read_text(encoding='utf-8'))
        self.assertEqual(set(report['jobs'][0]['output_sha256']),{'model.cas'})
