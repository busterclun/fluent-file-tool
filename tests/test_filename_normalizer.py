"""All fixtures are tiny synthetic files in TemporaryDirectory; never scans real CFD data."""
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest
import os
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import filename_normalizer as n


class NamingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='fluent_naming_test_')
        self.base=Path(self.tmp.name);self.root=self.base/'中文 含空格';self.root.mkdir()
        self.audit=self.base/'审计记录'
    def tearDown(self):self.tmp.cleanup()
    def put(self,name,body=None):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_bytes((body or '模拟文件:'+name).encode('utf-8'));return p
    def pair(self,base,step,h5=False,folder=''):
        end='.h5' if h5 else ''
        self.put(folder+base+'.cas'+end);self.put(folder+base+'-'+step+'.dat'+end)
    def plan(self,recursive=False,prefix='fuxian_fadhl'):return n.preview(self.root,prefix,recursive)
    def codes(self,p):return {x['code'] for x in p['issues']}
    def content(self):return {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
    def run_plan(self,p):
        self.assertEqual(p['issues'],[])
        r=n.execute(p,self.audit);self.assertEqual(r['status'],'verified',r);return r
    def test_01_complex_legacy_pair(self):
        self.pair('fuxian_fadhl-36.cas.h5-37','02500')
        p=self.plan();self.assertEqual({r['new'] for r in p['mapping']},{'fuxian_fadhl-02500.cas','fuxian_fadhl-02500.dat'})
        before={r['type']:n.fingerprint(self.root/r['old']) for r in p['mapping']}
        r=self.run_plan(p)
        for item in p['mapping']:self.assertEqual(n.fingerprint(self.root/item['new']),before[item['type']])
        manifest=Path(r['manifest']);self.assertTrue(manifest.exists())
        csv=(manifest.parent/'文件名对照.csv').read_text(encoding='utf-8-sig')
        for heading in ('batch','old_name','new_name','step','size','mtime_ns'):self.assertIn(heading,csv)
    def test_02_h5_extensions_preserved(self):
        self.pair('fuxian_fadhl-36','02400',True)
        p=self.plan();self.run_plan(p)
        self.assertEqual(set(self.content()),{'fuxian_fadhl-02400.cas.h5','fuxian_fadhl-02400.dat.h5'})
    def test_03_idempotence(self):
        self.pair('save','02500');self.run_plan(self.plan());before=self.content()
        p=self.plan();self.assertEqual(p['summary']['unchanged'],2);r=self.run_plan(p)
        self.assertEqual(r['success'],0);self.assertEqual(self.content(),before)
    def test_04_missing_case_or_data(self):
        self.put('lonely-00100.dat');self.put('orphan.cas')
        p=self.plan();self.assertTrue({'missing_case','unpaired_case'}<=self.codes(p))
        before=self.content()
        with self.assertRaises(ValueError):n.execute(p,self.audit)
        self.assertEqual(before,self.content())
    def test_05_shared_case(self):
        self.pair('save','00100');self.put('save-00200.dat')
        self.assertIn('case_shared',self.codes(self.plan()))
    def test_06_duplicate_numeric_and_padding(self):
        self.pair('save1','02500');self.pair('save2','2500')
        self.assertTrue({'duplicate_step','padding_mismatch'}<=self.codes(self.plan()))
    def test_07_target_collision(self):
        self.pair('save1','02500');self.pair('save2','02500')
        self.assertIn('duplicate_target',self.codes(self.plan()))
    def test_07b_existing_directory_target(self):
        self.pair('save','02500');(self.root/'fuxian_fadhl-02500.dat').mkdir()
        self.assertIn('target_exists',self.codes(self.plan()))
    def test_08_variable_intervals(self):
        nums=list(range(2400,4101,100))+[4190]+list(range(4200,5221,10))
        for i,num in enumerate(nums):self.pair('save'+str(i),f'{num:05d}')
        p=self.plan();self.assertEqual(p['issues'],[])
        self.assertEqual([(g['start'],g['end'],g['interval']) for g in p['summary']['intervals']],[(2400,4100,100),(4100,4190,90),(4190,5220,10)])
        self.assertIn('不能断言时间序列完整',p['notice']);self.run_plan(p)
    def test_09_failure_rollback(self):
        self.pair('save1','00100');self.pair('save2','00200');before=self.content();calls=0
        def failing(src,dst):
            nonlocal calls
            calls+=1
            if calls==3:raise OSError('模拟第三个改名失败')
            n.move_no_replace(src,dst)
        result=n.execute(self.plan(),self.audit,mover=failing)
        self.assertEqual(result['status'],'rolled_back',result);self.assertEqual(before,self.content())
        self.assertFalse(list(self.root.glob('*.tmp')))
    def test_09b_failed_rollback_and_later_recovery(self):
        self.pair('save1','00100');before=self.content();calls=0
        def failing(src,dst):
            nonlocal calls
            calls+=1
            if calls>=2:raise OSError('模拟磁盘暂时不可写')
            n.move_no_replace(src,dst)
        result=n.execute(self.plan(),self.audit,mover=failing)
        self.assertEqual(result['status'],'recovery_failed');self.assertTrue(result['recovery_errors'])
        self.assertTrue(result['states']);self.assertTrue(Path(result['manifest']).is_file())
        recovered=n.recover(result['manifest']);self.assertEqual(recovered['status'],'rolled_back',recovered)
        self.assertEqual(before,self.content())
    def test_10_unicode_spaces(self):
        self.pair('实验 一','00090');self.run_plan(self.plan(prefix='中文 前缀'))
        self.assertTrue((self.root/'中文 前缀-00090.cas').is_file())
    def test_11_nonrecursive_default(self):
        self.pair('root','00100');self.pair('child','00200',folder='子目录/')
        p=self.plan();self.assertEqual(p['summary']['fluent_files'],2);self.run_plan(p)
        self.assertTrue((self.root/'子目录/child.cas').exists())
        p=self.plan(True);self.assertEqual(p['summary']['fluent_files'],4);self.run_plan(p)
        self.assertTrue((self.root/'子目录/fuxian_fadhl-00200.cas').exists())
    def test_12_ambiguous_case(self):
        self.pair('save','00100');self.put('save-00100.cas')
        self.assertIn('ambiguous_case',self.codes(self.plan()))
    def test_13_mismatched_and_mixed_extensions(self):
        self.put('save.cas');self.put('save-00100.dat.h5')
        self.assertIn('format_mismatch',self.codes(self.plan()))
        self.pair('other','00200');self.assertIn('mixed_formats',self.codes(self.plan()))
    def test_14_unrecognized_step(self):
        self.put('save.dat');self.put('save.cas')
        self.assertIn('unrecognized_step',self.codes(self.plan()))
    def test_15_bad_prefix(self):
        self.pair('save','00100')
        for prefix in ('','x/y','x:y','x?y','x.','CON','LPT1'):
            with self.subTest(prefix=prefix):self.assertIn('prefix',self.codes(self.plan(prefix=prefix)))
    def test_16_changed_after_preview(self):
        self.pair('save','00100');p=self.plan();self.put('save.cas','changed')
        with self.assertRaisesRegex(ValueError,'预览后'):n.execute(p,self.audit)
        self.assertTrue((self.root/'save.cas').exists())
    def test_17_added_after_preview(self):
        self.pair('save','00100');p=self.plan();self.put('new.txt')
        with self.assertRaisesRegex(ValueError,'预览后'):n.execute(p,self.audit)
    def test_18_swap_and_reverse(self):
        self.pair('p-002','001');self.pair('p-001','002');before=self.content()
        p=self.plan(prefix='p');r=self.run_plan(p)
        self.assertEqual((self.root/'p-001.cas').read_bytes(),before['p-002.cas'])
        self.assertEqual((self.root/'p-002.cas').read_bytes(),before['p-001.cas'])
        self.assertTrue(r['verification']['old_paths_removed'])
    def test_18b_swap_rollback(self):
        self.pair('p-002','001');self.pair('p-001','002');before=self.content();calls=0
        def failing(src,dst):
            nonlocal calls
            calls+=1
            if calls==7:raise OSError('模拟交换提交失败')
            n.move_no_replace(src,dst)
        r=n.execute(self.plan(prefix='p'),self.audit,mover=failing)
        self.assertEqual(r['status'],'rolled_back',r);self.assertEqual(before,self.content())
    def test_19_unknown_file_unchanged(self):
        self.pair('save','00100');p=self.put('notes.txt');original=p.read_bytes();self.run_plan(self.plan())
        self.assertEqual(p.read_bytes(),original)
    def test_20_no_overwrite_race(self):
        self.pair('save','00100');calls=0
        def racing(src,dst):
            nonlocal calls
            calls+=1
            if calls==2:Path(dst).write_bytes(b'foreign')
            n.move_no_replace(src,dst)
        r=n.execute(self.plan(),self.audit,mover=racing)
        self.assertEqual(r['status'],'rolled_back',r)
        self.assertEqual((self.root/'fuxian_fadhl-00100.dat').read_bytes(),b'foreign')
        self.assertTrue((self.root/'save.cas').exists())
    def test_21_preserve_uppercase_extension(self):
        self.put('save.CAS.H5');self.put('save-00100.DAT.H5');self.run_plan(self.plan())
        self.assertTrue((self.root/'fuxian_fadhl-00100.CAS.H5').exists())
    def test_22_recursive_duplicate_blocked(self):
        self.pair('save','00100');self.pair('save','00100',folder='sub/')
        self.assertIn('duplicate_step',self.codes(self.plan(True)))
    def test_23_changed_during_execute_restored(self):
        self.pair('save','00100');calls=0
        def racing(src,dst):
            nonlocal calls
            calls+=1
            n.move_no_replace(src,dst)
            if calls==2:self.put('unrelated.txt')
        r=n.execute(self.plan(),self.audit,mover=racing)
        self.assertEqual(r['status'],'rolled_back',r)
        self.assertIn('执行后',r['error']);self.assertTrue((self.root/'save.cas').exists())
    def test_24_process_crash_before_journal_update(self):
        self.pair('save','00100');before=self.content()
        script=self.base/'crash.py'
        script.write_text('import sys,os\n'
            f'sys.path.insert(0,{str(Path(n.__file__).parent)!r})\n'
            'import filename_normalizer as n\n'
            'def crash(src,dst):\n    n.move_no_replace(src,dst)\n    os._exit(55)\n'
            f'n.execute(n.preview({str(self.root)!r},"fuxian_fadhl"),{str(self.audit)!r},mover=crash)\n',encoding='utf-8')
        completed=subprocess.run([sys.executable,str(script)],creationflags=subprocess.CREATE_NO_WINDOW,timeout=20)
        self.assertEqual(completed.returncode,55)
        manifest=next(self.audit.glob('*/batch.json'))
        r=n.recover(manifest);self.assertEqual(r['status'],'rolled_back',r)
        self.assertEqual(before,self.content());self.assertFalse(list(self.audit.glob('*.lock')))
    def test_25_active_lock_blocks(self):
        self.pair('save','00100');self.audit.mkdir();p=self.plan()
        with n.batch_lock(self.audit,self.root,p['batch']):
            with self.assertRaisesRegex(ValueError,'批次锁'):n.execute(p,self.audit)
    def test_26_modified_temp_leaves_evidence_recovers_others(self):
        self.pair('save','00100');calls=0;temp_path=None
        def racing(src,dst):
            nonlocal calls,temp_path
            calls+=1;n.move_no_replace(src,dst)
            if calls==1:temp_path=Path(dst);temp_path.write_bytes(b'externally changed')
        r=n.execute(self.plan(),self.audit,mover=racing)
        self.assertEqual(r['status'],'recovery_failed')
        self.assertTrue((self.root/'save-00100.dat').exists())
        self.assertEqual(temp_path.read_bytes(),b'externally changed')
        self.assertTrue(any(s['observed'] for s in r['states']))
    def test_27_old_report_warning(self):
        self.pair('save','00100');self.put('conversion_report.json','{}')
        self.assertTrue(self.plan()['warnings'])
    def test_28_pending_recovery_blocks_new_batch(self):
        self.pair('save','00100');self.put('.fluent-rename-interrupted.tmp')
        self.assertIn('pending_recovery',self.codes(self.plan()))

    def test_29_normal_batch_is_direct(self):
        self.pair('save','00100');moves=[]
        def observe(src,dst):
            moves.append(Path(dst).name);n.move_no_replace(src,dst)
        result=n.execute(self.plan(),self.audit,mover=observe)
        self.assertEqual(result['status'],'verified');self.assertEqual(result['strategy'],'direct')
        self.assertEqual(len(moves),2);self.assertFalse(any(name.endswith('.tmp') for name in moves))
    def test_30_exfat_identity_is_not_compared(self):
        p=self.put('sample.cas')
        with patch.object(n,'filesystem_type',return_value='EXFAT'):
            self.assertEqual(n.fingerprint(p)['inode'],0)


    def initial_pair(self,h5=False,name='case1'):
        for ext in ('cas','dat'):self.put(name+'.'+ext+('.h5' if h5 else ''))
    def test_initial_requires_explicit_opt_in(self):
        self.initial_pair();before=self.content();p=self.plan()
        self.assertIn('unrecognized_step',self.codes(p))
        with self.assertRaises(ValueError):n.execute(p,self.audit)
        self.assertEqual(before,self.content())
    def test_initial_legacy_with_numbered_files(self):
        self.initial_pair();self.pair('case1-1','00010')
        p=n.preview(self.root,'out',initial_step='0');self.assertEqual(p['issues'],[])
        self.assertEqual(p['assigned_initial'][0]['step'],'00000')
        before={r['new']:(self.root/r['old']).read_bytes() for r in p['mapping']}
        self.run_plan(p);self.assertEqual(self.content(),before)
        repeated=n.preview(self.root,'out',initial_step='0')
        self.assertEqual(repeated['issues'],[]);self.assertEqual(repeated['summary']['unchanged'],4)
    def test_initial_h5_and_custom_number(self):
        self.initial_pair(True);self.pair('case1-1','00010',True)
        p=n.preview(self.root,'out',initial_step='5');self.run_plan(p)
        self.assertTrue((self.root/'out-00005.cas.h5').exists())
        self.assertTrue((self.root/'out-00005.dat.h5').exists())
    def test_initial_only_defaults_five_digits(self):
        self.initial_pair();p=n.preview(self.root,'out',initial_step='0');self.run_plan(p)
        self.assertEqual(set(self.content()),{'out-00000.cas','out-00000.dat'})
    def test_initial_zero_collision_blocks_all(self):
        self.initial_pair();self.pair('saved','00000');before=self.content()
        p=n.preview(self.root,'out',initial_step='0');self.assertIn('duplicate_step',self.codes(p))
        with self.assertRaises(ValueError):n.execute(p,self.audit)
        self.assertEqual(before,self.content())
    def test_multiple_unnumbered_pairs_block_all(self):
        self.initial_pair();self.initial_pair(name='other')
        p=n.preview(self.root,'out',initial_step='0');self.assertIn('duplicate_step',self.codes(p))
    def test_initial_invalid_number(self):
        self.initial_pair()
        for value in ('','-1','1.5','abc','１２','0'*101,0):
            with self.subTest(value=value):
                p=n.preview(self.root,'out',initial_step=value);self.assertIn('initial_step',self.codes(p))
                with self.assertRaises(ValueError):n.execute(p,self.audit)
    def test_initial_missing_case_and_format_mismatch(self):
        self.put('case1.dat');p=n.preview(self.root,'out',initial_step='0')
        self.assertIn('missing_case',self.codes(p))
        self.put('case1.cas.h5');p=n.preview(self.root,'out',initial_step='0')
        self.assertIn('format_mismatch',self.codes(p))
    def test_initial_does_not_change_existing_numbered_padding(self):
        self.initial_pair();self.pair('save','10');p=n.preview(self.root,'out',initial_step='0')
        self.assertEqual(p['issues'],[]);self.assertEqual({r['step'] for r in p['mapping']},{'0','10'})
        self.pair('other','00020');p=n.preview(self.root,'out',initial_step='0')
        self.assertIn('padding_mismatch',self.codes(p))
    def test_initial_shared_case_remains_blocked(self):
        self.initial_pair();self.put('case1-00010.dat')
        self.assertIn('case_shared',self.codes(n.preview(self.root,'out',initial_step='0')))


@unittest.skipUnless(os.environ.get('FLUENT_TEST_VOLUME'),'Optional real volume tests')
class VolumeNamingTests(NamingTests):
    def setUp(self):
        self.volume=Path(os.environ['FLUENT_TEST_VOLUME']).resolve()
        self.tmp=tempfile.TemporaryDirectory(prefix='FluentRenameTest_',dir=self.volume)
        self.base=Path(self.tmp.name).resolve()
        assert self.base.parent==self.volume and self.base.name.startswith('FluentRenameTest_')
        self.root=self.base/'中文 含空格';self.root.mkdir();self.audit=self.base/'audit'
    def tearDown(self):
        assert self.base.resolve().parent==self.volume and self.base.name.startswith('FluentRenameTest_')
        super().tearDown()


if __name__=='__main__':unittest.main(verbosity=2)
