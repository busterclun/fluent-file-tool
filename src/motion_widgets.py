"""Reusable nonblocking Tk motion. No timer threads and no filesystem side effects."""
import math
import time
import tkinter as tk
import sys
import ctypes
import customtkinter as ctk


def clamp(x):return max(0.,min(1.,x))
def ease(x):return 1-(1-clamp(x))**3
def mix(a,b,t):
    t=clamp(t)
    return '#'+''.join(f'{round(int(a[i:i+2],16)*(1-t)+int(b[i:i+2],16)*t):02x}' for i in (1,3,5))


def rounded(canvas,x0,y0,x1,y1,r,**options):
    r=min(r,(x1-x0)/2,(y1-y0)/2)
    return canvas.create_polygon(x0+r,y0,x1-r,y0,x1,y0,x1,y0+r,x1,y1-r,x1,y1,x1-r,y1,x0+r,y1,x0,y1,x0,y1-r,x0,y0+r,x0,y0,smooth=True,splinesteps=20,**options)


def feedback_frame(seconds,width,height):
    """Logical-pixel frame geometry; shared by native rendering and exported previews."""
    t=max(0,seconds);shrink=ease(t/.24);expand=ease((t-1.05)/.22)
    fraction=shrink*(1-expand)
    w=width+(height-width)*fraction
    tick=clamp((t-.29)/.27)*(1-expand)
    points=[(-8,0),(-2,6),(9,-7)]
    lengths=[math.dist(points[i],points[i+1]) for i in range(2)]
    remaining=sum(lengths)*tick;path=[points[0]]
    for i,length in enumerate(lengths):
        part=min(1,remaining/length)
        if part<=0:break
        path.append(tuple(points[i][j]+(points[i+1][j]-points[i][j])*part for j in range(2)))
        remaining-=length
    burst=clamp((t-.56)/.43);particles=[]
    if .56<t<.99:
        for i in range(10):
            angle=2*math.pi*i/10-.25
            radius=height/2+5+19*ease(burst)
            particles.append((math.cos(angle)*radius,math.sin(angle)*radius,2.4*(1-burst),1-burst))
    stage='shrink' if t<.24 else 'check' if t<.56 else 'particles' if t<.99 else 'restore'
    return dict(width=w,radius=8+(height/2-8)*fraction,check=path if tick>0 else [],particles=particles,
                text_alpha=max(1-clamp(t/.13),expand),success_mix=fraction,stage=stage,done=t>=1.28)


class CompletionButton(ctk.CTkButton):
    """Call success() after real success; confirm=True delays closing a dialog until feedback finishes."""
    def __init__(self,master,*,command=None,confirm=False,**kwargs):
        self._action=command;self._confirm=confirm;self._effect_timer=None;self._effect_canvas=None
        self.feedback_running=False;self.feedback_pending=False;self.feedback_count=0;self.feedback_stages=[]
        self._finish_callback=None;self._effect_window=None;self._effect_overlay=None;self._effect_mask=None
        super().__init__(master,command=self._dispatch,**kwargs)
        tk.Misc.bind(self,'<Map>',self._mapped,add='+')
        tk.Misc.bind(self,'<Unmap>',self._unmapped,add='+')
    def _dispatch(self):
        if self.feedback_running:return
        if self._confirm:self.success(on_complete=self._action)
        elif self._action:return self._action()
    def configure(self,require_redraw=False,**kwargs):
        if 'command' in kwargs:self._action=kwargs.pop('command');kwargs['command']=self._dispatch
        return super().configure(require_redraw=require_redraw,**kwargs)
    def _mapped(self,event=None):
        if self.feedback_pending and not self.feedback_running:self.after_idle(self._start_feedback)
    def _unmapped(self,event=None):
        if self.feedback_running:
            callback=self._finish_callback;self.reset_feedback()
            if callback:callback()
    def reset_feedback(self):
        if self._effect_timer:
            try:self.after_cancel(self._effect_timer)
            except tk.TclError:pass
        self._effect_timer=None
        if self._effect_canvas:
            try:self._effect_canvas.destroy()
            except tk.TclError:pass
        if self._effect_overlay:
            try:self._effect_overlay.destroy()
            except tk.TclError:pass
        if self._effect_mask:
            try:self._effect_mask.destroy()
            except tk.TclError:pass
        self._effect_overlay=None;self._effect_mask=None
        self._effect_canvas=None;self.feedback_running=False;self.feedback_pending=False;self._finish_callback=None
    def success(self,on_complete=None,*,animate_hidden=False):
        if self.feedback_running:return
        self.feedback_count+=1;self.feedback_pending=True;self._finish_callback=on_complete
        if self.winfo_ismapped() or animate_hidden:self._start_feedback()
    def _start_feedback(self):
        if not self.feedback_pending or self.feedback_running or not self.winfo_exists():return
        self.feedback_pending=False;self.feedback_running=True;self.feedback_stages=[]
        self._effect_window=self.winfo_toplevel();self._effect_started=time.monotonic()
        self._effect_scale=self._get_widget_scaling()
        self._effect_width=max(self.winfo_width(),int(self._desired_width*self._effect_scale))
        self._effect_height=max(self.winfo_height(),int(self._desired_height*self._effect_scale))
        self._effect_pad=int(28*self._effect_scale)
        self._effect_bg=self._apply_appearance_mode(self.cget('bg_color'))
        self._effect_color=self._apply_appearance_mode(self.cget('fg_color'))
        if self._effect_color=='transparent':self._effect_color='#5267A2'
        self._effect_text_color=self._apply_appearance_mode(self.cget('text_color'))
        # Tk accepts named colors (notably the primary button's 'white').
        # Interpolation needs canonical RGB rather than slicing the original string.
        for attr in ('_effect_bg','_effect_color','_effect_text_color'):
            rgb=self.winfo_rgb(getattr(self,attr))
            setattr(self,attr,'#'+''.join(f'{v//257:02x}' for v in rgb))
        self._effect_text=self.cget('text')
        # Mask only this button's original drawing; never paint over its siblings.
        self._effect_mask=tk.Canvas(self,highlightthickness=0,bd=0,bg=self._effect_bg)
        self._effect_mask.place(x=0,y=0,relwidth=1,relheight=1)
        self._effect_mask.tk.call('raise',self._effect_mask._w)
        self._effect_canvas=self._effect_mask
        # Tk canvases have no transparent background. Use a color-keyed owned
        # window for the floating shape and particles, with no opaque padding.
        if sys.platform=='win32' and self.winfo_ismapped():
            overlay=None
            try:
                key='#FF00FE'
                overlay=tk.Toplevel(self._effect_window);overlay.withdraw()
                overlay.overrideredirect(True);overlay.transient(self._effect_window)
                overlay.configure(bg=key);overlay.attributes('-transparentcolor',key)
                overlay.attributes('-alpha',self._effect_window.attributes('-alpha'))
                overlay.update_idletasks()
                # Do not take keyboard focus or intercept clicks outside the button.
                user32=ctypes.WinDLL('user32',use_last_error=True)
                user32.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user32.GetAncestor.restype=ctypes.c_void_p
                user32.GetWindowLongW.argtypes=[ctypes.c_void_p,ctypes.c_int];user32.GetWindowLongW.restype=ctypes.c_long
                user32.SetWindowLongW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_long];user32.SetWindowLongW.restype=ctypes.c_long
                hwnd=user32.GetAncestor(overlay.winfo_id(),2)
                style=user32.GetWindowLongW(hwnd,-20)
                user32.SetWindowLongW(hwnd,-20,style|0x08000000|0x00000020|0x00000080)
                self._effect_overlay=overlay
                self._effect_canvas=tk.Canvas(overlay,highlightthickness=0,bd=0,bg=key)
                self._effect_canvas.pack(fill='both',expand=True)
            except (tk.TclError,OSError):
                if overlay:overlay.destroy()
                self._effect_overlay=None;self._effect_canvas=self._effect_mask
        if self._effect_overlay is None:self._effect_pad=0
        self._effect_canvas.bind('<Button-1>',lambda e:'break')
        self._tick_feedback()
    def _tick_feedback(self):
        if not self.feedback_running or not self._effect_canvas:return
        elapsed=time.monotonic()-self._effect_started;s=self._effect_scale
        f=feedback_frame(elapsed,self._effect_width/s,self._effect_height/s)
        if not self.feedback_stages or self.feedback_stages[-1]!=f['stage']:self.feedback_stages.append(f['stage'])
        if f['done']:
            callback=self._finish_callback;self.reset_feedback()
            if callback:callback()
            return
        cv=self._effect_canvas;p=self._effect_pad
        if self._effect_overlay:
            x=self.winfo_rootx()-p;y=self.winfo_rooty()-p
            self._effect_overlay.geometry(f'{self._effect_width+2*p}x{self._effect_height+2*p}{x:+d}{y:+d}')
            self._effect_overlay.deiconify()
        cv.delete('all')
        cx=p+self._effect_width/2;cy=p+self._effect_height/2
        fill=mix(self._effect_color,'#537D72',f['success_mix'])
        rounded(cv,cx-f['width']*s/2,cy-self._effect_height/2,cx+f['width']*s/2,cy+self._effect_height/2,f['radius']*s,fill=fill,outline='')
        if len(f['check'])>1:cv.create_line(*[v for pt in f['check'] for v in (cx+pt[0]*s,cy+pt[1]*s)],fill='#FFFFFF',width=2.6*s,capstyle='round',joinstyle='round')
        for i,(dx,dy,r,alpha) in enumerate(f['particles']):
            color=mix(self._effect_bg,('#7186B4','#73A294','#A7B5CF')[i%3],alpha)
            cv.create_oval(cx+(dx-r)*s,cy+(dy-r)*s,cx+(dx+r)*s,cy+(dy+r)*s,fill=color,outline='')
        if f['text_alpha']>.01:
            cv.create_text(cx,cy,text=self._effect_text,font=self._font,fill=mix(fill,self._effect_text_color,f['text_alpha']))
        self._effect_timer=self.after(16,self._tick_feedback)
    def destroy(self):
        self.reset_feedback();super().destroy()


class SlidingSwitch(ctk.CTkFrame):
    def __init__(self,master,values,command=None,width=244,height=38,**kwargs):
        super().__init__(master,width=width,height=height,fg_color='transparent',**kwargs)
        self.values=list(values);self.command=command;self.value=self.values[0];self.position=0.;self._timer=None;self._dragged=False
        self.canvas=tk.Canvas(self,highlightthickness=0,bd=0,bg='#FFFFFF',takefocus=1,cursor='hand2')
        self.canvas.place(relwidth=1,relheight=1)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Left>',lambda e:self.set(self.values[0]));self.canvas.bind('<Right>',lambda e:self.set(self.values[-1]))
        self.canvas.bind('<space>',lambda e:self.set(self.values[1-self.values.index(self.value)]))
        self.canvas.bind('<Return>',lambda e:self.set(self.values[1-self.values.index(self.value)]))
        self.canvas.bind('<FocusIn>',lambda e:self.draw());self.canvas.bind('<FocusOut>',lambda e:self.draw())
    def cancel(self):
        if self._timer:
            try:self.after_cancel(self._timer)
            except tk.TclError:pass
        self._timer=None
    def set(self,value,animate=True):
        if value not in self.values:raise ValueError(value)
        self.cancel();changed=value!=self.value;self.value=value
        start=self.position;target=float(self.values.index(value));began=time.monotonic()
        if changed and self.command:self.command(value)
        def tick():
            t=clamp((time.monotonic()-began)/.2)
            self.position=start+(target-start)*ease(t);self.draw()
            if t<1:self._timer=self.after(16,tick)
            else:self._timer=None
        if animate:tick()
        else:self.position=target;self.draw()
    def press(self,event):
        self.cancel();self._press_x=event.x;self._dragged=False;self.canvas.focus_set()
    def drag(self,event):
        if abs(event.x-self._press_x)>3:self._dragged=True
        if self._dragged:
            w=max(1,self.canvas.winfo_width());self.position=clamp((event.x-w/4)/(w/2));self.draw()
    def release(self,event):
        index=round(self.position) if self._dragged else int(event.x>=self.canvas.winfo_width()/2)
        self.set(self.values[index])
    def draw(self):
        c=self.canvas;w=c.winfo_width();h=c.winfo_height()
        if w<2 or h<2:return
        c.delete('all');s=self._get_widget_scaling();inset=4*s;cell=(w-2*inset)/2
        rounded(c,0,0,w,h,h/2,fill='#EAF0F5',outline='')
        x=inset+self.position*cell
        rounded(c,x,inset+1*s,x+cell,h-inset+1*s,(h-2*inset)/2,fill='#D9E1EB',outline='')
        rounded(c,x,inset,x+cell,h-inset,(h-2*inset)/2,fill='#FFFFFF',outline='')
        for i,label in enumerate(self.values):
            c.create_text(inset+cell*(i+.5),h/2,text=label,font=('Microsoft YaHei UI',int(-12*s),'bold' if label==self.value else 'normal'),fill='#435D91' if label==self.value else '#748092')
        if c.focus_get()==c:rounded(c,1,1,w-1,h-1,h/2,fill='',outline='#9AAECF',width=1)
    def destroy(self):self.cancel();super().destroy()


class SlidingTabs(ctk.CTkFrame):
    """Small CTkTabview-compatible host, with a draggable/snap-to-position capsule in the card header."""
    def __init__(self,master,switch_parent,**kwargs):
        super().__init__(master,fg_color='transparent',**kwargs)
        self.pages={};self.current=None;self.grid_rowconfigure(0,weight=1);self.grid_columnconfigure(0,weight=1)
        self.switch=SlidingSwitch(switch_parent,['改名前后','检查详情'],command=self._show)
        self.switch.pack(side='right')
    def add(self,name):
        page=ctk.CTkFrame(self,fg_color='#FFFFFF',corner_radius=0);self.pages[name]=page
        if self.current is None:self._show(name)
        return page
    def tab(self,name):return self.pages[name]
    def _show(self,name):
        if name not in self.pages:return
        for key,page in self.pages.items():
            if key==name:page.grid(row=0,column=0,sticky='nsew')
            else:page.grid_remove()
        self.current=name
    def set(self,name):self._show(name);self.switch.set(name)
    def get(self):return self.current
