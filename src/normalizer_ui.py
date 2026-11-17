"""Optional standalone normalization page for the existing CustomTkinter application."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, ttk

import customtkinter as ctk
import filename_normalizer as engine
from motion_widgets import CompletionButton, SlidingTabs


class NormalizerPage(ctk.CTkFrame):
    def __init__(self,parent,owner,audit_directory,colors):
        super().__init__(parent,fg_color='transparent')
        self.owner=owner;self.c=colors;self.audit_directory=Path(audit_directory)
        self.plan=None;self.recovery_manifest=None;self.last_manifest=None
        self.running=False;self.events=queue.Queue();self.last_auto_prefix=''
        self.enabled=tk.BooleanVar(value=False);self.recursive=tk.BooleanVar(value=False)
        self.directory=tk.StringVar();self.prefix=tk.StringVar()
        self.status=tk.StringVar(value='先开启右上方的开关，再选择要整理的文件夹。')
        self.stats=tk.StringVar(value='检查后，这里会显示找到多少文件、多少组配对，以及哪些名称需要修改。')
        self.name_example=tk.StringVar();self.scope_hint=tk.StringVar()
        self.grid_columnconfigure(0,weight=1);self.grid_rowconfigure(3,weight=1)
        head=ctk.CTkFrame(self,fg_color='transparent');head.grid(row=0,column=0,sticky='ew',pady=(0,10))
        title=ctk.CTkFrame(head,fg_color='transparent');title.pack(side='left')
        owner.label(title,'整理文件名',20,True).pack(anchor='w')
        owner.label(title,'把名称统一为“前缀-时间步”，只改名字，文件内容和位置都保留。',12,color=colors['muted'],height=20).pack(anchor='w',pady=(2,0))
        self.toggle=ctk.CTkSwitch(head,text='启用文件名整理',variable=self.enabled,font=owner.font(13),progress_color=colors['blue'],text_color=colors['text'],command=self.invalidate)
        self.toggle.pack(side='right',padx=(14,0))
        fields=owner.card(self);fields.grid(row=1,column=0,sticky='ew',pady=(0,10));fields.grid_columnconfigure(0,weight=1)
        self.step_headers=[]
        self.step_header(fields,'01','选择文件与命名',0)
        pathrow=ctk.CTkFrame(fields,fg_color='transparent');pathrow.grid(row=1,column=0,sticky='ew',padx=18,pady=(0,12));pathrow.grid_columnconfigure(1,weight=1)
        owner.label(pathrow,'文件夹',13,True,width=78).grid(row=0,column=0,padx=(0,14))
        self.path_entry=ctk.CTkEntry(pathrow,textvariable=self.directory,placeholder_text='选择存放 CAS / DAT 文件的文件夹',height=36,font=owner.font(13),border_color=colors['border'])
        self.path_entry.grid(row=0,column=1,sticky='ew')
        self.browse_button=self.button(pathrow,'选择文件夹',self.browse,110);self.browse_button.grid(row=0,column=2,padx=(10,0))
        lower=ctk.CTkFrame(fields,fg_color='transparent');lower.grid(row=2,column=0,sticky='ew',padx=18,pady=(0,16))
        lower.grid_columnconfigure(0,weight=1,uniform='options');lower.grid_columnconfigure(1,weight=1,uniform='options')
        naming=ctk.CTkFrame(lower,fg_color='transparent');naming.grid(row=0,column=0,sticky='nsew',padx=(0,24))
        owner.label(naming,'文件名的统一开头',13,True).pack(anchor='w',pady=(0,5))
        self.prefix_entry=ctk.CTkEntry(naming,textvariable=self.prefix,placeholder_text='例如 fuxian_fadhl',height=34,font=owner.font(13),border_color=colors['border']);self.prefix_entry.pack(fill='x')
        self.example_label=owner.label(naming,textvariable=self.name_example,size=12,color=colors['muted'],wraplength=400);self.example_label.pack(anchor='w',pady=(5,0))
        naming.bind('<Configure>',lambda e:self.example_label.configure(wraplength=max(100,e.width)))
        scope=ctk.CTkFrame(lower,fg_color='transparent');scope.grid(row=0,column=1,sticky='nsew')
        owner.label(scope,'要整理哪些文件？',13,True).pack(anchor='w',pady=(0,8))
        choices=ctk.CTkFrame(scope,fg_color='transparent');choices.pack(fill='x')
        self.scope_buttons=[]
        for text,value in [('只整理这一层',False),('连同里面的文件夹',True)]:
            radio=ctk.CTkRadioButton(choices,text=text,variable=self.recursive,value=value,font=owner.font(12),radiobutton_width=16,radiobutton_height=16,border_width_checked=5,border_width_unchecked=2,fg_color=colors['blue'],text_color=colors['text'],command=self.invalidate)
            radio.pack(side='left',padx=(0,12));self.scope_buttons.append(radio)
        self.scope_label=owner.label(scope,textvariable=self.scope_hint,size=12,color=colors['muted'],wraplength=420);self.scope_label.pack(anchor='w',pady=(8,0))
        scope.bind('<Configure>',lambda e:self.scope_label.configure(wraplength=max(100,e.width)))
        self.settings=[self.path_entry,self.prefix_entry,self.browse_button,*self.scope_buttons]
        preview_card=owner.card(self);preview_card.grid(row=2,column=0,rowspan=2,sticky='nsew');preview_card.grid_columnconfigure(0,weight=1);preview_card.grid_rowconfigure(2,weight=1)
        preview_header=self.step_header(preview_card,'02','核对改名前后',0)
        info=ctk.CTkFrame(preview_card,fg_color='transparent');info.grid(row=1,column=0,sticky='ew',padx=18,pady=(0,6))
        owner.label(info,textvariable=self.stats,size=12,color=colors['muted'],height=20).pack(anchor='w',pady=(3,0))
        self.status_label=owner.label(info,textvariable=self.status,size=12,color=colors['muted'],wraplength=950,height=20)
        self.status_label.pack(anchor='w',pady=(3,4))
        info.bind('<Configure>',lambda e:self.status_label.configure(wraplength=max(300,e.width-8)))
        tabs=SlidingTabs(preview_card,preview_header,height=150)
        tabs.grid(row=2,column=0,sticky='nsew',padx=18,pady=(0,16));tabs.add('改名前后');tabs.add('检查详情');self.tabs=tabs
        frame=tabs.tab('改名前后');frame.grid_columnconfigure(0,weight=1);frame.grid_rowconfigure(0,weight=1)
        scale=self._get_widget_scaling()
        style=ttk.Style();style.configure('Normalize.Treeview',font=('Microsoft YaHei UI',11),rowheight=int(34*scale),background=colors['white'],fieldbackground=colors['white'],foreground=colors['text'])
        style.configure('Normalize.Treeview.Heading',font=('Microsoft YaHei UI',11,'bold'))
        self.table=ttk.Treeview(frame,columns=('old','new','folder','step','status'),show='headings',style='Normalize.Treeview',selectmode='browse')
        for key,title,width in [('old','现在的文件名',300),('new','改名后的文件名',280),('folder','所在文件夹',150),('step','时间步',78),('status','结果',90)]:
            self.table.heading(key,text=title);self.table.column(key,width=int(width*scale),minwidth=int(60*scale),anchor='w' if key in ('old','new','folder') else 'center',stretch=key in ('old','new'))
        self.table.grid(row=0,column=0,sticky='nsew')
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.table.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.table.xview);sx.grid(row=1,column=0,sticky='ew')
        self.table.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.table.tag_configure('alternate',background='#F7F9FC')
        self.table.bind('<Double-1>',self.show_file_detail)
        self.table_widgets=[self.table,sy,sx];self.row_details={}
        self.empty=ctk.CTkFrame(frame,fg_color=colors['white'])
        owner.label(self.empty,'先预览，再决定是否改名',17,True).pack(anchor='center')
        owner.label(self.empty,'选择文件夹后，点击下方“检查文件并预览”。\n这里会并排显示每个文件现在的名字和新名字。',13,color=colors['muted']).pack(anchor='center',pady=10)
        owner.label(self.empty,'检查和预览不会修改文件。',12,color=colors['muted']).pack(anchor='center')
        self.details=ctk.CTkTextbox(tabs.tab('检查详情'),font=owner.font(12),wrap='word',fg_color=colors['soft'],text_color=colors['text'])
        self.details.pack(fill='both',expand=True);self.set_details(engine.NOTICE)
        foot=ctk.CTkFrame(self,fg_color='transparent');foot.grid(row=4,column=0,sticky='ew',pady=(10,0))
        self.more_button=self.button(foot,'更多操作…',self.more_actions,108);self.more_button.pack(side='left')
        self.execute_button=self.button(foot,'确认改名',self.execute,160,True,completion=True);self.execute_button.pack(side='right')
        self.scan_button=self.button(foot,'检查文件并预览',self.scan,158,completion=True);self.scan_button.pack(side='right',padx=(0,10))
        owner.label(self,'时间步来自 DAT 文件名；不会启动 Fluent 读取内部计算结果。双击表格行可查看完整名称与位置。',11,color=colors['muted'],wraplength=950).grid(row=5,column=0,sticky='w',pady=(8,0))
        self.directory.trace_add('write',self.directory_changed);self.prefix.trace_add('write',self.invalidate)
        self.update_hints();self.show_empty();self.sync();self.after(100,self.poll)

    def step_header(self,parent,number,title,row):
        header=ctk.CTkFrame(parent,fg_color='transparent');header.grid(row=row,column=0,sticky='ew',padx=18,pady=(14,12))
        badge=ctk.CTkLabel(header,text=number,width=30,height=30,corner_radius=9,fg_color=self.c['tint'],text_color=self.c['blue'],font=self.owner.font(12,True))
        badge.pack(side='left')
        label=self.owner.label(header,title,15,True);label.pack(side='left',padx=(12,0))
        self.step_headers.append((header,badge,label))
        return header

    def button(self,parent,text,command,width,primary=False,completion=False,confirm=False):
        cls=CompletionButton if completion or confirm else ctk.CTkButton
        extra={'confirm':confirm} if completion or confirm else {}
        return cls(parent,text=text,command=command,anchor='center',width=width,height=36,font=self.owner.font(13),**extra,
                             fg_color=self.c['blue'] if primary else self.c['white'],text_color='white' if primary else self.c['text'],
                             hover_color=self.c['hover'] if primary else '#E9EDF4',border_width=0 if primary else 1,border_color=self.c['border'])

    def sync(self):
        busy=self.owner.busy
        enabled=self.enabled.get() and not busy
        self.toggle.configure(state='disabled' if busy else 'normal')
        for widget in self.settings+[self.scan_button]:widget.configure(state='normal' if enabled else 'disabled')
        ready=enabled and ((self.plan is not None and not self.plan['issues']) or self.recovery_manifest is not None)
        label='确认恢复原名' if self.recovery_manifest else '确认改名'
        if ready and self.plan is not None:
            count=self.plan['summary']['changes'];label=f'确认改名（{count} 个）' if count else '无需改名 · 保存记录'
        self.execute_button.configure(state='normal' if ready else 'disabled',text=label,fg_color=self.c['blue'] if ready else '#E5EAF1',text_color_disabled='#8A95A4')
        self.scan_button.configure(fg_color=self.c['blue'] if enabled and not ready else self.c['white'],text_color='white' if enabled and not ready else self.c['text'])
        self.more_button.configure(state='disabled' if busy else 'normal')

    def update_hints(self):
        prefix=self.prefix.get() or 'fuxian_fadhl'
        self.name_example.set(f'例如：{prefix}-02500.cas / .dat\n时间步和扩展名按原文件保留。')
        self.scope_hint.set('也整理里面各层文件夹，例如 series_01 中的文件；文件不会搬到一起。' if self.recursive.get() else '只检查所选文件夹直接放着的文件，里面的文件夹不会处理。')

    def show_empty(self):
        for widget in self.table_widgets:widget.grid_remove()
        self.empty.place(relx=.5,rely=.5,anchor='center')

    def show_table(self):
        self.empty.place_forget()
        for widget in self.table_widgets:widget.grid()

    def add_row(self,old,new,step,status):
        folder=Path(old).parent.as_posix()
        item=self.table.insert('','end',values=(Path(old).name,Path(new).name if new!='—' else '—',
                                               '所选文件夹' if folder=='.' else folder,step,status),
                               tags=('alternate',) if len(self.row_details)%2 else ())
        self.row_details[item]=(old,new,step,status)

    def show_file_detail(self,event=None):
        selected=self.table.selection()
        if not selected or selected[0] not in self.row_details:return
        old,new,step,_=self.row_details[selected[0]];status=self.table.set(selected[0],'status')
        window=ctk.CTkToplevel(self.owner);window.title('改名详情');window.geometry('700x360');window.transient(self.owner)
        self.owner.label(window,'文件仍在原来的文件夹，只修改名字',16,True).pack(anchor='w',padx=24,pady=20)
        box=ctk.CTkTextbox(window,font=self.owner.font(13),wrap='word');box.pack(fill='both',expand=True,padx=24,pady=(0,16))
        base=Path(getattr(self,'display_root',self.directory.get()))
        box.insert('1.0',f'现在的文件名\n{Path(old).name}\n\n改名后的文件名\n{Path(new).name if new!="—" else "尚未确定"}\n\n所在位置\n{base / Path(old).parent}\n\n时间步：{step}    结果：{status}')
        box.configure(state='disabled');self.button(window,'关闭',window.destroy,90,confirm=True).pack(pady=(0,18));window.bind('<Escape>',lambda e:window.destroy())

    def more_actions(self):
        if self.owner.busy:return
        window=ctk.CTkToplevel(self.owner);window.title('更多操作');window.geometry('520x300');window.resizable(False,False);window.transient(self.owner)
        self.owner.label(window,'记录与恢复',18,True).pack(anchor='w',padx=24,pady=(20,8))
        self.owner.label(window,'日常改名只需“检查文件并预览”和“确认改名”。',12,color=self.c['muted']).pack(anchor='w',padx=24,pady=(0,14))
        def call(action):window.destroy();action()
        record=self.button(window,'查看本次改名记录',lambda:call(self.open_record),200)
        record.pack(anchor='w',padx=24);record.configure(state='normal' if self.last_manifest else 'disabled')
        self.owner.label(window,'包含改名前后的名称；完成一次操作后可查看。',12,color=self.c['muted']).pack(anchor='w',padx=24,pady=(5,14))
        restore=self.button(window,'恢复未完成的改名…',lambda:call(self.load_recovery),200)
        restore.pack(anchor='w',padx=24);restore.configure(state='normal' if self.enabled.get() else 'disabled')
        self.owner.label(window,'上次改名异常中断时使用，选择 batch.json 恢复原名。',12,color=self.c['muted']).pack(anchor='w',padx=24,pady=(5,14))
        window.bind('<Escape>',lambda e:window.destroy())

    def invalidate(self,*_):
        self.scan_button.reset_feedback();self.execute_button.reset_feedback()
        self.plan=None;self.recovery_manifest=None
        self.update_hints();self.show_empty();self.row_details.clear();self.table.delete(*self.table.get_children())
        self.stats.set('检查后显示文件数量、CASE / DAT 配对和需要修改的名称。')
        self.status.set('选好文件夹和名称后，点击“检查文件并预览”。' if self.enabled.get() else '先开启右上方的开关，再选择要整理的文件夹。')
        self.sync()

    def directory_changed(self,*_):
        default=Path(self.directory.get()).name if self.directory.get() else ''
        if not self.prefix.get() or self.prefix.get()==self.last_auto_prefix:self.prefix.set(default)
        self.last_auto_prefix=default;self.invalidate()

    def browse(self):
        path=filedialog.askdirectory(parent=self.owner,title='选择需要规范化文件名的目录')
        if path:self.directory.set(path)

    def set_details(self,text):
        self.details.configure(state='normal');self.details.delete('1.0','end');self.details.insert('1.0',text);self.details.configure(state='disabled')

    def run_job(self,kind,call):
        if self.owner.busy:return
        self.scan_button.reset_feedback();self.execute_button.reset_feedback()
        for button in self.owner.completion_buttons.values():button.reset_feedback()
        self.running=True;self.owner.busy=True
        for control in self.owner.controls:control.configure(state='disabled')
        self.sync();self.status.set('正在扫描与检查…' if kind=='preview' else '正在执行，请等待当前批次完成…')
        def work():
            try:self.events.put((kind,call(),None))
            except Exception as exc:self.events.put((kind,None,str(exc)))
        threading.Thread(target=work,daemon=True).start()

    def scan(self):
        if not self.enabled.get() or self.owner.busy:return
        directory=self.directory.get().strip();prefix=self.prefix.get();recursive=self.recursive.get()
        self.plan=None;self.recovery_manifest=None
        if not directory:self.status.set('请先选择文件目录。');self.sync();return
        self.run_job('preview',lambda:engine.preview(directory,prefix,recursive))

    def execute(self):
        if not self.enabled.get() or self.owner.busy:return
        if self.recovery_manifest:
            manifest=self.recovery_manifest;self.recovery_manifest=None
            self.run_job('recover',lambda:engine.recover(manifest))
        elif self.plan is not None and not self.plan['issues']:
            plan=self.plan;self.plan=None
            self.run_job('execute',lambda:engine.execute(plan,self.audit_directory))

    def show_plan(self,plan):
        self.display_root=plan['root']
        self.table.delete(*self.table.get_children());self.row_details.clear();self.show_table()
        for row in plan['mapping']:
            self.add_row(row['old'],row['new'],row['step'],'无需修改' if row['old']==row['new'] else '请先处理问题' if plan['issues'] else '将改名')
        mapped={r['old'] for r in plan['mapping']}
        for path in plan['snapshot']:
            if engine.split_name(Path(path).name) and path not in mapped:self.add_row(path,'—','—','需要处理')
        s=plan['summary'];self.stats.set(f'找到 {s["fluent_files"]} 个 Fluent 文件  ·  配成 {s["pair_count"]} 组 CASE / DAT  ·  将改名 {s["changes"]} 个  ·  无需修改 {s["unchanged"]} 个  ·  问题 {len(plan["issues"])} 项')
        span='—' if not s['step_range'] else f'{s["step_range"][0]}–{s["step_range"][1]}'
        intervals='；'.join(f'{g["start"]}→{g["end"]}：间隔 {g["interval"]}（{g["count"]} 次）' for g in s['intervals']) or '少于两个不同时间步，暂无间隔'
        text=f'扫描文件总数：{s["scanned_files"]}（其中 Fluent 文件 {s["fluent_files"]}）\n时间步数：{s["step_count"]}\n时间步范围：{span}\n采样间隔：{intervals}\n\n{engine.NOTICE}\n\n'
        for warning in plan.get('warnings',[]):text+='提示：'+warning+'\n\n'
        guidance={
            'missing_case':'请把同一次保存对应的 CASE 文件放到这个文件夹，再重新检查。',
            'unpaired_case':'请补齐对应的 DAT 数据文件，或将不属于本次整理的 CASE 单独放到其他文件夹。',
            'ambiguous_case':'有多个 CASE 都可能对应这个 DAT，请先确认哪一组才是配套文件。',
            'case_shared':'同一个 CASE 被多个 DAT 使用，不能直接改成多个时间步名称，请先核对原始配对。',
            'duplicate_step':'不同批次可能使用相同时间步。请分别选择各批次的文件夹整理。',
            'padding_mismatch':'编号补零长度不同，请先核对源文件；工具不会擅自补零或去零。',
            'format_mismatch':'一组文件应同时为 CAS/DAT，或同时为 CAS.H5/DAT.H5。',
            'mixed_formats':'请把传统格式和 H5 格式分开检查。',
            'target_exists':'新名字已被占用，请核实已有文件；工具不会覆盖它。',
            'pending_recovery':'请通过“更多操作 → 恢复未完成的改名”处理上次操作。',
            'prefix':'请修改“文件名的统一开头”，去掉 /、\\、:、*、? 等不能用于文件名的字符。'}
        for i,item in enumerate(plan['issues'],1):
            text+=f'{i}. {item["message"]}\n   '+'\n   '.join(item['paths'])+'\n'
            if item['code'] in guidance:text+='处理方法：'+guidance[item['code']]+'\n'
            text+='\n'
        if not plan['issues']:text+='文件配对和名称检查通过。请核对“改名前后”，再点击“确认改名”。'
        self.set_details(text)
        short_intervals=' / '.join(str(g['interval']) for g in s['intervals'][:6]) or '—'
        self.status.set((f'有 {len(plan["issues"])} 项问题需要先处理，所有文件暂不改名。' if plan['issues'] else '预览已准备好；确认后才会修改文件名。')+f' 时间步 {span} · 间隔 {short_intervals}'+('…（见检查详情）' if len(s['intervals'])>6 else ''))
        self.tabs.set('检查详情' if plan['issues'] or plan.get('warnings') else '改名前后')

    def show_result(self,result):
        self.last_manifest=result['manifest'];plan=result['plan'];self.show_plan(plan)
        status=result['status'];success=result.get('success',0) if status=='verified' else 0
        unchanged=sum(r['old']==r['new'] for r in result['rows'])
        errors=([result['error']] if result.get('error') else [])+result.get('recovery_errors',[])
        headline={'verified':'完成 · 文件名和元数据核验通过','rolled_back':'本批次已恢复原文件名','recovery_failed':'恢复未完成 · 请查看下方当前状态和失败项'}.get(status,status)
        self.status.set(headline)
        s=plan['summary'];self.stats.set(f'扫描 {s["scanned_files"]} 文件    时间步 {s["step_count"]}    配对 {s["pair_count"]}    成功 {success}    无需修改 {unchanged}    问题 {len(errors)}')
        text=self.details.get('1.0','end').replace('文件配对和名称检查通过。请核对“改名前后”，再点击“确认改名”。','')+'\n\n'+headline+f'\n成功：{success}；无需修改：{unchanged}；问题：{len(errors)}\n对照清单：{Path(self.last_manifest).parent / "文件名对照.csv"}\n批次校验及恢复记录：{self.last_manifest}\n'
        if errors:text+='\n问题详情：\n'+'\n'.join(errors)
        if result.get('states'):
            text+='\n\n当前文件状态：\n'+'\n'.join(f'{s["old"]} → 当前：{s["found"] or "未能按原元数据定位"}' for s in result['states'])
            if status=='recovery_failed':text+='\n\n候选路径及当前元数据：\n'+json.dumps(result['states'],ensure_ascii=False,indent=2)
        self.set_details(text);self.tabs.set('检查详情')
        if status=='verified':
            for item,row in zip(self.table.get_children(),plan['mapping']):self.table.set(item,'status','无需修改' if row['old']==row['new'] else '已完成')
        else:
            for item in self.table.get_children():self.table.set(item,'status','已恢复' if status=='rolled_back' else '待恢复')

    def load_recovery(self):
        if not self.enabled.get() or self.owner.busy:return
        selected=filedialog.askopenfilename(parent=self.owner,title='选择失败批次的 batch.json',initialdir=str(self.audit_directory),filetypes=[('批次记录','batch.json')])
        if not selected:return
        self.plan=None;self.recovery_manifest=None;self.sync()
        try:
            record=json.loads(Path(selected).read_text(encoding='utf-8'))
            if record.get('schema')!=1 or record.get('status') not in ('prepared','executing','rolling_back','recovery_failed'):raise ValueError('这不是可恢复的未完成批次。')
            self.plan=None;self.recovery_manifest=None;self.show_plan(record['plan'])
            states=engine.locate_states(Path(record['plan']['root']),record['rows'])
            self.set_details('恢复预览：将以下文件恢复为原文件名。确认后点击“确认恢复原名”。\n\n'+'\n'.join(f'{s["found"]} → {s["old"]}' for s in states)+f'\n\n记录：{selected}')
            self.tabs.set('检查详情');self.status.set('已加载恢复预览 · 等待执行恢复。')
            self.recovery_manifest=selected;self.last_manifest=selected;self.sync()
        except Exception as exc:self.set_details('无法加载恢复批次：'+str(exc));self.tabs.set('检查详情')

    def open_record(self):
        if self.last_manifest:os.startfile(str(Path(self.last_manifest).parent))

    def poll(self):
        try:
            kind,result,error=self.events.get_nowait()
            self.running=False;self.owner.busy=False
            for control in self.owner.controls:control.configure(state='normal')
            if error:
                self.plan=None;self.recovery_manifest=None;self.status.set('已阻止执行或任务失败 · 请查看问题详情。')
                self.set_details(error+'\n\n'+engine.NOTICE);self.tabs.set('检查详情')
            elif kind=='preview':self.plan=result;self.show_plan(result)
            else:self.show_result(result)
            self.sync()
            if not error:
                if kind=='preview' and not result['issues']:self.scan_button.success()
                elif kind=='execute' and result['status']=='verified':self.execute_button.success()
                elif kind=='recover' and result['status']=='rolled_back' and not result.get('recovery_errors'):self.execute_button.success()
        except queue.Empty:pass
        self.after(100,self.poll)
