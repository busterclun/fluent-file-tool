"""Fluent File Tool desktop application."""
import json, os, queue, re, subprocess, sys, threading, traceback
import tkinter as tk
from tkinter import filedialog, messagebox
from pathlib import Path
from datetime import datetime
import customtkinter as ctk
from normalizer_ui import NormalizerPage
from motion_widgets import CompletionButton
from smooth_scroll import SmoothScrollableFrame

BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent.parent
WORKER=(Path(sys._MEIPASS)/'runtime'/'worker.py') if getattr(sys,'frozen',False) else Path(__file__).resolve().parent/'worker.py'
CONFIG=BASE/'设置.json'
DEFAULTS=dict(input='',output=str(BASE/'转换结果'),prefix='fuxian_fadhl',digits='5',dimension='2',version='24.1.0',fluent_root='',python='')
C=dict(bg='#F4F6F9',white='#FFFFFF',text='#283445',muted='#748092',border='#DDE3EC',blue='#5267A2',hover='#43588F',tint='#EEF2F8',soft='#F8FAFC',green='#537D72')
ctk.set_appearance_mode('light')
ctk.set_default_color_theme('blue')

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self._initializing=True;self._close_requested=False
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.title('Fluent 文件转换工具 · v1.0.3');self.geometry('1120x820');self.minsize(1000,720)
        self.configure(fg_color=C['bg'])
        try:config={**DEFAULTS,**json.loads(CONFIG.read_text(encoding='utf-8'))}
        except (OSError,ValueError):config=DEFAULTS
        self.vars={k:tk.StringVar(value=str(v)) for k,v in config.items()}
        self.events=queue.Queue();self.busy=False;self.controls=[];self.proc=None;self.stop_path=None;self.completion_buttons={}
        self.active_page='work';self.status=tk.StringVar(value='准备就绪');self.detail=tk.StringVar(value='先扫描文件，确认配对后开始转换。')
        self.env_status=tk.StringVar(value='环境尚未检查')
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(2,weight=1)
        header=ctk.CTkFrame(self,fg_color=C['white'],corner_radius=0);header.grid(row=0,column=0,sticky='ew')
        mark=ctk.CTkLabel(header,text='F',width=40,height=40,corner_radius=10,fg_color=C['blue'],text_color='white',font=self.font(23,True));mark.pack(side='left',padx=(28,14),pady=20)
        brand=ctk.CTkFrame(header,fg_color='transparent');brand.pack(side='left')
        self.label(brand,'Fluent 文件转换工具',22,True).pack(anchor='w')
        self.label(brand,'保留原名转换 · 独立整理文件名',12,color=C['muted']).pack(anchor='w',pady=(2,0))
        ctk.CTkButton(header,anchor='center',text='使用说明',width=88,height=34,fg_color=C['soft'],text_color=C['muted'],hover_color='#E9EDF3',font=self.font(12),command=self.open_help).pack(side='right',padx=28)
        nav=ctk.CTkFrame(self,fg_color=C['bg']);nav.grid(row=1,column=0,sticky='ew',padx=28,pady=(18,14))
        self.nav_buttons={}
        for name,text in [('work','转换工作台'),('normalize','整理文件名'),('environment','运行环境')]:
            b=ctk.CTkButton(nav,anchor='center',text=text,height=36,width=124,corner_radius=8,font=self.font(14,True),command=lambda n=name:self.show_page(n));b.pack(side='left',padx=(0,8));self.nav_buttons[name]=b
        self.label(nav,'本地处理 · 双精度转换',12,color=C['muted']).pack(side='right')
        self.content=ctk.CTkFrame(self,fg_color='transparent');self.content.grid(row=2,column=0,sticky='nsew',padx=28,pady=(0,18));self.content.grid_columnconfigure(0,weight=1);self.content.grid_rowconfigure(0,weight=1)
        self.pages={}
        self.build_work();self.build_environment();self.build_footer();self.build_log()
        self.normalizer=NormalizerPage(self.content,self,BASE/'命名记录',C);self.pages['normalize']=self.normalizer
        self.preview();self.show_page('work')
        self.after(100,self.poll);self._initializing=False
        # CTk.mainloop performs its own initial window setup before entering Tk.
        # An idle callback can run inside that setup; defer until the event loop starts.
        if self._close_requested:self.after(100,self.close)
    def font(self,size=14,bold=False):return ctk.CTkFont(family='Microsoft YaHei UI',size=size,weight='bold' if bold else 'normal')
    def label(self,parent,text='',size=14,bold=False,color=None,**kw):
        return ctk.CTkLabel(parent,text=text,font=self.font(size,bold),text_color=color or C['text'],anchor='w',justify='left',**kw)
    def card(self,parent):return ctk.CTkFrame(parent,fg_color=C['white'],corner_radius=12,border_width=1,border_color=C['border'])
    def section(self,parent,n,title,subtitle):
        head=ctk.CTkFrame(parent,fg_color='transparent');head.pack(fill='x',padx=22,pady=(18,14))
        self.label(head,n,12,True,C['blue'],width=30).pack(side='left',anchor='n',pady=3)
        text=ctk.CTkFrame(head,fg_color='transparent');text.pack(side='left',fill='x',expand=True)
        self.label(text,title,16,True).pack(anchor='w')
        if subtitle:self.label(text,subtitle,12,color=C['muted']).pack(anchor='w',pady=(3,0))
    def button(self,parent,text,command,primary=False,width=100,completion=None):
        cls=CompletionButton if completion else ctk.CTkButton
        b=cls(parent,anchor='center',text=text,command=command,height=38,width=width,corner_radius=8,
            fg_color=C['blue'] if primary else C['white'],hover_color=C['hover'] if primary else '#F0F3F8',
            text_color='white' if primary else C['text'],border_width=0 if primary else 1,border_color=C['border'],font=self.font(13))
        self.controls.append(b)
        if completion:self.completion_buttons[completion]=b
        return b
    def entry(self,parent,key,width=None):
        kw={} if width is None else {'width':width}
        e=ctk.CTkEntry(parent,textvariable=self.vars[key],height=38,corner_radius=8,border_width=1,border_color=C['border'],fg_color=C['white'],text_color=C['text'],font=self.font(13),**kw)
        self.controls.append(e);return e
    def path_field(self,parent,key,title,helper,example=None):
        field=ctk.CTkFrame(parent,fg_color='transparent');field.pack(fill='x',padx=22,pady=(0,16))
        self.label(field,title,13,True).pack(anchor='w',pady=(0,6))
        row=ctk.CTkFrame(field,fg_color='transparent');row.pack(fill='x');row.grid_columnconfigure(0,weight=1)
        self.entry(row,key).grid(row=0,column=0,sticky='ew')
        self.button(row,'选择文件' if key=='python' else '选择文件夹',lambda:self.browse(key),width=96).grid(row=0,column=1,padx=(10,0))
        self.label(field,helper,12,color=C['muted'],wraplength=640).pack(anchor='w',pady=(6,0))
        if example:self.label(field,example,12,color=C['muted'],wraplength=640).pack(anchor='w',pady=(3,0))
    def build_work(self):
        page=ctk.CTkFrame(self.content,fg_color='transparent');self.pages['work']=page
        page.grid_columnconfigure(0,weight=1);page.grid_rowconfigure(0,weight=1)
        left=SmoothScrollableFrame(page,fg_color='transparent',corner_radius=0,scrollbar_button_color='#D5DBE4');left.grid(row=0,column=0,sticky='nsew',padx=(0,18));self.work_scroll=left
        right=ctk.CTkFrame(page,fg_color='transparent',width=290);right.grid(row=0,column=1,sticky='ns');right.grid_propagate(False);right.pack_propagate(False)
        files=self.card(left);files.pack(fill='x',pady=(0,14))
        self.section(files,'01','选择文件','读取 H5 文件，输出独立的 CAS / DAT 结果。')
        self.path_field(files,'input','H5 输入文件夹','选择同时包含 .cas.h5 和 .dat.h5 的文件夹。')
        self.path_field(files,'output','结果保存位置','保留原名的 CAS / DAT 和验证报告保存在这里。')
        naming=self.card(left);naming.pack(fill='x',pady=(0,14))
        self.section(naming,'02','模型设置','选择与原始模型一致的维度；转换保留原文件名。')
        dims=ctk.CTkFrame(naming,fg_color='transparent');dims.pack(fill='x',padx=22,pady=(0,20))
        self.label(dims,'原始模型维度',13,True).pack(anchor='w',pady=(0,10))
        row=ctk.CTkFrame(dims,fg_color='transparent');row.pack(fill='x')
        for text,val in [('二维模型  2D','2'),('三维模型  3D','3')]:
            radio=ctk.CTkRadioButton(row,text=text,variable=self.vars['dimension'],value=val,font=self.font(13),fg_color=C['blue'],hover_color=C['hover'],border_color='#A0AABA',text_color=C['text'],radiobutton_width=18,radiobutton_height=18)
            radio.pack(side='left',padx=(0,28));self.controls.append(radio)
        self.label(dims,'与原始 Fluent 模型保持一致；此选项不会改变模型维度。',12,color=C['muted']).pack(anchor='w',pady=(10,0))
        preview=self.card(right);preview.pack(fill='x',pady=(0,14))
        self.label(preview,'输出预览',15,True).pack(anchor='w',padx=20,pady=(20,3))
        self.label(preview,'只移除末尾的 .h5',12,color=C['muted']).pack(anchor='w',padx=20)
        tile=ctk.CTkFrame(preview,fg_color=C['tint'],corner_radius=8);tile.pack(fill='x',padx=16,pady=16)
        self.example=self.label(tile,'',13,color=C['blue'],wraplength=240);self.example.pack(anchor='w',padx=14,pady=14)
        self.label(preview,'原文件保留；不添加前缀或时间步。',12,color=C['muted']).pack(anchor='w',padx=20,pady=(0,18))
        grouping=self.card(right);grouping.pack(fill='x',pady=(0,14))
        self.label(grouping,'需要改名时再整理',14,True).pack(anchor='w',padx=20,pady=(18,8))
        self.label(grouping,'转换后到“整理文件名”页面，\n设置前缀、查看预览并确认改名。',12,color=C['muted'],wraplength=245).pack(anchor='w',padx=20,pady=(0,18))
    def build_environment(self):
        page=SmoothScrollableFrame(self.content,fg_color='transparent',corner_radius=0);self.pages['environment']=page
        intro=ctk.CTkFrame(page,fg_color='transparent');intro.pack(fill='x',pady=(2,14))
        self.label(intro,'连接本机 Fluent',20,True).pack(anchor='w')
        self.label(intro,'通常只需配置一次。这里的两条路径分别指向 Fluent 安装文件夹和 Python 程序。',13,color=C['muted']).pack(anchor='w',pady=(5,0))
        env=self.card(page);env.pack(fill='x')
        self.section(env,'01','Fluent 安装位置','用于启动求解器进行真实格式转换。')
        self.path_field(env,'fluent_root','Fluent 安装根目录 · 选择文件夹','选择版本根文件夹，例如 v241。其内部应有 fluent 文件夹。','示例：E:\\Program Files\\ANSYS Inc\\v241')
        self.section(env,'02','Python 运行环境','用于运行自动化脚本并连接 Fluent。')
        self.path_field(env,'python','Python 解释器 · 选择 python.exe','请选择已经安装 ansys-fluent-core 和 numpy 的 Python 环境。','示例：C:\\FluentPython\\Scripts\\python.exe')
        self.section(env,'03','Fluent 版本号','填写软件版本代码，与上面的安装目录对应。')
        version=ctk.CTkFrame(env,fg_color='transparent');version.pack(fill='x',padx=22,pady=(0,20))
        self.entry(version,'version',180).pack(anchor='w')
        self.label(version,'格式：两位年份.发布序号.0，例如 24.1.0（使用英文句点）。',12,color=C['muted']).pack(anchor='w',pady=(7,6))
        sample=ctk.CTkFrame(version,fg_color=C['soft'],corner_radius=8);sample.pack(fill='x')
        self.label(sample,'2024 R1  →  24.1.0  →  v241        2024 R2  →  24.2.0  →  v242',13,color=C['muted']).pack(anchor='w',padx=14,pady=12)
        bottom=ctk.CTkFrame(page,fg_color='transparent');bottom.pack(fill='x',pady=16)
        self.button(bottom,'检查环境',self.check_environment,width=110,completion='environment').pack(side='left')
        self.button(bottom,'保存设置',self.save_settings,primary=True,width=110,completion='save').pack(side='left',padx=10)
        self.label(bottom,textvariable=self.env_status,size=12,color=C['muted']).pack(side='left',padx=6)
        self.label(page,'环境检查验证路径和 Python 依赖；许可证会在真正启动 Fluent 时检查。',12,color=C['muted']).pack(anchor='w',pady=(0,16))
    def build_footer(self):
        footer=ctk.CTkFrame(self,fg_color=C['white'],corner_radius=0);footer.grid(row=3,column=0,sticky='ew');self.footer=footer
        top=ctk.CTkFrame(footer,fg_color='transparent');top.pack(fill='x',padx=28,pady=(16,8))
        text=ctk.CTkFrame(top,fg_color='transparent');text.pack(side='left',fill='x',expand=True)
        self.label(text,textvariable=self.status,size=14,bold=True,wraplength=650).pack(anchor='w')
        self.label(text,textvariable=self.detail,size=12,color=C['muted'],wraplength=650).pack(anchor='w',pady=(3,0))
        ctk.CTkButton(top,anchor='center',text='日志详情',width=80,fg_color='transparent',text_color=C['muted'],hover_color=C['soft'],font=self.font(12),command=self.show_log).pack(side='right')
        self.progress=ctk.CTkProgressBar(footer,height=3,corner_radius=0,fg_color='#EDF0F5',progress_color=C['blue'],mode='determinate');self.progress.pack(fill='x');self.progress.set(0)
        actions=ctk.CTkFrame(footer,fg_color='transparent');actions.pack(fill='x',padx=28,pady=(12,16))
        self.button(actions,'扫描文件',lambda:self.run('scan'),width=105,completion='scan').pack(side='left',padx=(0,8))
        self.button(actions,'整理文件名',lambda:self.show_page('normalize'),width=140).pack(side='left')
        self.stop=ctk.CTkButton(actions,anchor='center',text='本组完成后停止',width=140,height=38,fg_color=C['soft'],text_color=C['muted'],hover_color='#E8ECF2',font=self.font(13),state='disabled',command=self.request_stop);self.stop.pack(side='left',padx=8)
        self.button(actions,'开始转换',lambda:self.run('convert'),primary=True,width=166,completion='convert').pack(side='right',padx=(8,0))
        ctk.CTkButton(actions,anchor='center',text='打开结果',width=94,height=38,fg_color='transparent',text_color=C['blue'],hover_color=C['tint'],font=self.font(13),command=self.open_output).pack(side='right')
    def build_log(self):
        self.log_window=ctk.CTkToplevel(self);self.log_window.title('运行日志');self.log_window.geometry('900x520');self.log_window.withdraw();self.log_window.protocol('WM_DELETE_WINDOW',self.log_window.withdraw)
        self.log=ctk.CTkTextbox(self.log_window,font=('Consolas',13),fg_color=C['soft'],text_color=C['text'],wrap='word');self.log.pack(fill='both',expand=True,padx=16,pady=16);self.log.configure(state='disabled')
    def show_log(self):self.log_window.deiconify();self.log_window.lift()
    def show_page(self,name):
        self.active_page=name
        if name=='normalize':self.footer.grid_remove();self.normalizer.sync()
        else:self.footer.grid()
        for key,p in self.pages.items():
            if key==name:p.grid(row=0,column=0,sticky='nsew')
            else:p.grid_remove()
        for key,b in self.nav_buttons.items():b.configure(fg_color=C['white'] if key==name else 'transparent',text_color=C['blue'] if key==name else C['muted'],hover_color='#E9EDF4',border_width=1 if key==name else 0,border_color=C['border'])
    def preview(self,*_):
        self.example.configure(text='case2_VOF.cas.h5 → case2_VOF.cas\ncase2_VOF.dat.h5 → case2_VOF.dat')
    def browse(self,key):
        if key=='python':val=filedialog.askopenfilename(title='选择已安装 PyFluent 的 python.exe',filetypes=[('Python 程序','python.exe'),('可执行程序','*.exe')])
        else:val=filedialog.askdirectory(title='选择版本根目录，例如 v241' if key=='fluent_root' else '选择文件夹')
        if val:self.vars[key].set(val)
    def open_output(self):
        path=Path(self.vars['output'].get())
        if path.is_dir():os.startfile(path)
        else:messagebox.showinfo('输出目录','输出文件夹尚未创建。',parent=self)
    def open_help(self, *, show=True):
        window=getattr(self,'help_window',None)
        if window is None or not window.winfo_exists():
            window=ctk.CTkToplevel(self);window.withdraw();self.help_window=window
            window.title('使用说明');window.geometry('620x570');window.minsize(560,450)
            window.configure(fg_color=C['bg']);window.transient(self)
            window.protocol('WM_DELETE_WINDOW',window.destroy)
            window.bind('<Escape>',lambda event:window.destroy())
            header=ctk.CTkFrame(window,fg_color=C['white'],corner_radius=0)
            header.pack(fill='x')
            self.label(header,'几步完成转换',20,True).pack(anchor='w',padx=24,pady=(22,4))
            self.label(header,'读取 H5 → 转换并验证 → 保留原名输出',12,color=C['muted']).pack(anchor='w',padx=24,pady=(0,18))
            footer=ctk.CTkFrame(window,fg_color=C['white'],corner_radius=0)
            footer.pack(side='bottom',fill='x')
            CompletionButton(footer,text='知道了',anchor='center',width=108,height=36,fg_color=C['blue'],hover_color=C['hover'],font=self.font(13),command=window.destroy,confirm=True).pack(side='right',padx=24,pady=14)
            body=SmoothScrollableFrame(window,fg_color='transparent',corner_radius=0)
            body.pack(fill='both',expand=True,padx=18,pady=12)
            sections=[
                ('怎么用',
                 '1. 选择 H5 输入文件夹和独立的结果文件夹。\n'
                 '2. 选择原始模型维度，转换保留源文件名。\n'
                 '3. 先“扫描文件”，再“开始转换”；完成后“打开结果”。'),
                ('选项怎么填',
                 '命名规则：只移除末尾 .h5；统一前缀请到“整理文件名”设置。\n'
                 '模型维度：与原模型一致，二维选 2D，三维选 3D。\n'
                 '一个 CASE 对应多个 DAT 时，按 DAT 原名分目录保存，文件名不变。'),
                ('开始前需要知道',
                 '只支持 Fluent 的 .cas.h5 / .dat.h5；原始文件会保留。\n'
                 '转换需要本机 Fluent、可用许可证和已配置的 Python 环境；首次使用可到“运行环境”检查。\n'
                 '如需统一名称，请在转换完成后进入“整理文件名”页面。\n'
                 '中途停止请用“本组完成后停止”；出现问题可查看“日志详情”。'),
                ('独立规范化已有文件名',
                 '进入“整理文件名”，开启开关，选择文件夹和文件名的统一开头。点击“检查文件并预览”，核对新旧名称后“确认改名”。\n'
                 '默认只整理所选文件夹这一层；选择“连同里面的文件夹”才会整理各层文件夹内的文件。\n'
                 '只读取文件名和元数据，不读取实际求解时间步，也不需要 Fluent。异常恢复入口在“更多操作”。')]
            for title,content in sections:
                card=self.card(body);card.pack(fill='x',pady=(0,12))
                self.label(card,title,14,True).pack(anchor='w',padx=16,pady=(14,6))
                copy=self.label(card,content,12,color=C['muted'],wraplength=500)
                copy.pack(fill='x',padx=16,pady=(0,14))
                card.bind('<Configure>',lambda event,label=copy:label.configure(wraplength=max(100,event.width-32)))
        if show:window.deiconify();window.lift();window.focus_set()
    def configuration(self):return {k:v.get().strip() for k,v in self.vars.items()}
    def validate_environment(self,cfg):
        if not Path(cfg['python']).is_file():raise ValueError('Python 路径应选择实际的 python.exe 文件。')
        if Path(cfg['python']).name.lower()!='python.exe':raise ValueError('请选择 python.exe，不是文件夹或 pythonw.exe。')
        if not re.fullmatch(r'\d{2}\.[12]\.0',cfg['version']):raise ValueError('版本号格式示例：2024 R1 填 24.1.0，2024 R2 填 24.2.0。')
        root=Path(cfg['fluent_root'])
        if not (root/'fluent/ntbin/win64/fluent.exe').is_file():raise ValueError('Fluent 安装目录应选到 v241 这一级，其内部需有 fluent 文件夹。')
        expected='v'+cfg['version'].replace('.','')[:-1]
        if re.fullmatch(r'v\d{3}',root.name.lower()) and root.name.lower()!=expected:raise ValueError(f'版本号与目录不一致：{cfg["version"]} 对应 {expected}。')
    def save_settings(self):
        try:
            cfg=self.configuration();self.validate_environment(cfg)
            CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8');self.env_status.set('设置已保存')
            self.completion_buttons['save'].success()
        except ValueError as e:messagebox.showerror('环境设置需要调整',str(e),parent=self)
    def check_environment(self):
        if self.busy:return
        cfg=self.configuration()
        try:self.validate_environment(cfg)
        except ValueError as e:messagebox.showerror('环境设置需要调整',str(e),parent=self);return
        cmd=[cfg['python'],'-u','-c',"import sys, numpy, ansys.fluent.core as p; print('Python '+sys.version.split()[0]+' | PyFluent '+p.__version__+' | NumPy '+numpy.__version__)"]
        self.start_job(cmd,'environment')
    def run(self,action):
        if self.busy:return
        cfg=self.configuration()
        try:
            if not Path(cfg['python']).is_file():raise ValueError('请在“运行环境”中选择包含 PyFluent 的 Python 解释器。')
            if action=='convert':self.validate_environment(cfg)
            if not cfg['input'] or not Path(cfg['input']).is_dir():raise ValueError('请选择有效的 H5 输入文件夹。')
            if not cfg['output']:raise ValueError('请选择结果保存位置。')
            if Path(cfg['input']).resolve()==Path(cfg['output']).resolve():raise ValueError('输出目录必须与输入目录不同。')
        except ValueError as e:messagebox.showerror('设置需要调整',str(e),parent=self);return
        CONFIG.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
        cmd=[cfg['python'],'-u',str(WORKER),action]
        for key in ['input','output','prefix','digits','dimension','version','fluent_root']:cmd.extend(['--'+key.replace('_','-'),cfg[key]])
        self.start_job(cmd,action)
    def start_job(self,cmd,action):
        for button in self.completion_buttons.values():button.reset_feedback()
        self.normalizer.scan_button.reset_feedback();self.normalizer.execute_button.reset_feedback()
        logs=BASE/'运行日志';logs.mkdir(exist_ok=True);stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        self.stop_path=logs/(stamp+'.stop');self.log_path=logs/(stamp+'.log')
        if action!='environment':cmd+=['--stop-file',str(self.stop_path)]
        self.busy=True
        self.normalizer.sync()
        for c in self.controls:c.configure(state='disabled')
        self.stop.configure(state='normal' if action=='convert' else 'disabled')
        self.progress.configure(mode='indeterminate');self.progress.start()
        self.status.set({'scan':'正在扫描文件','convert':'正在转换并回读验证','environment':'正在检查运行环境'}[action])
        self.detail.set('详细过程已记录，可点击右侧“日志详情”查看。')
        self.append('\n任务开始：'+action+'\n日志：'+str(self.log_path)+'\n')
        threading.Thread(target=self.execute,args=(cmd,action),daemon=True).start()
    def execute(self,cmd,action):
        try:
            env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONIOENCODING']='utf-8'
            with self.log_path.open('w',encoding='utf-8') as log:
                self.proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',env=env,creationflags=subprocess.CREATE_NO_WINDOW,cwd=str(BASE))
                for line in self.proc.stdout:log.write(line);log.flush();self.events.put(('line',line))
                rc=self.proc.wait()
            self.events.put(('done',(rc,action)))
        except Exception as e:self.events.put(('line',str(e)+'\n'));self.events.put(('done',(1,action)))
    def append(self,text):
        self.log.configure(state='normal');self.log.insert('end',text);self.log.see('end');self.log.configure(state='disabled')
    def poll(self):
        try:
            for _ in range(100):
                kind,data=self.events.get_nowait()
                if kind=='line':
                    self.append(data)
                    if 'VERIFIED' in data:self.detail.set(data.strip()[:140])
                    if data.startswith('发现 '):self.detail.set(data.strip())
                else:
                    rc,action=data;self.busy=False;self.progress.stop();self.progress.configure(mode='determinate');self.progress.set(1 if rc==0 else 0);self.stop.configure(state='disabled')
                    for c in self.controls:c.configure(state='normal')
                    self.normalizer.sync()
                    self.status.set('扫描完成' if rc==0 and action=='scan' else '环境检查通过' if rc==0 and action=='environment' else '完成 · 点击“打开结果”查看文件' if rc==0 else '已停止 · 下次使用相同目录可继续' if rc==2 else '任务失败 · 详细原因见日志')
                    if action=='environment':self.env_status.set('路径与 Python 依赖检查通过' if rc==0 else '环境检查失败，请查看日志')
                    if action not in ['scan','environment']:self.detail.set('转换结果和验证报告已保存；文件名保持原样。' if rc==0 else '已完成文件会保留。查看日志后，可使用相同目录继续。')
                    self.append('\n'+self.status.get()+'\n')
                    if rc==1:self.show_log()
                    if rc==0 and action in self.completion_buttons:self.completion_buttons[action].success()
        except queue.Empty:pass
        except Exception:
            self.report_callback_exception(*sys.exc_info())
        finally:
            self.after(100,self.poll)
    def report_callback_exception(self,exc_type,exc_value,exc_traceback):
        # Optional UI feedback must never leave a blocking overlay behind.
        for button in self.completion_buttons.values():button.reset_feedback()
        for button in (self.normalizer.scan_button,self.normalizer.execute_button):button.reset_feedback()
        text='界面反馈异常（不代表转换失败）：\n'+''.join(traceback.format_exception(exc_type,exc_value,exc_traceback))
        try:
            folder=BASE/'运行日志';folder.mkdir(exist_ok=True)
            with (folder/'界面错误.log').open('a',encoding='utf-8') as stream:stream.write(text+'\n')
            self.append('\n'+text+'\n')
        except (OSError,tk.TclError):pass
    def request_stop(self):
        if self.busy and self.stop_path:self.stop_path.write_text('stop',encoding='utf-8');self.stop.configure(state='disabled');self.status.set('已请求停止');self.detail.set('正在等待当前组安全完成…')
    def close(self):
        if self._initializing:
            self._close_requested=True
            return
        if self.busy:messagebox.showinfo('任务正在运行','请等待当前任务结束；Fluent 转换任务可点击“本组完成后停止”。',parent=self);return
        self.destroy()

if __name__=='__main__':
    app=App()
    app.mainloop()
