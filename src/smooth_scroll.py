"""Short, finite wheel interpolation without exponential easing or inertia."""
import sys
import time
import tkinter as tk
import customtkinter as ctk


def wheel_pixels(delta,scale=1.,platform=sys.platform):
    # Windows sends +/-120 per notch, but precision devices also send partial notches.
    return -float(delta)*(84./120. if platform.startswith('win') else 2.)*scale


class SmoothScrollableFrame(ctk.CTkScrollableFrame):
    # Each notch has its own deadline. Later input never prolongs earlier motion.
    _wheel_duration=.060
    _wheel_lead=.008
    _frame_ms=8
    def __init__(self,*args,**kwargs):
        self._owned_bindings=[];self._scroll_timer=None;self._target_px=None;self._last_direction=0
        self._position_px=None;self._rendered_px=None;self._segments=[]
        self._scroll_destroyed=False;self._content_size=None;self._scrollbar_range=None
        super().__init__(*args,**kwargs)
        self._parent_canvas.configure(yscrollincrement=1)
        # Moving a canvas window emits Configure even when its size stays unchanged.
        # CTk's default binding recalculates the region on every movement.
        self.bind('<Configure>',self._update_scroll_region)
        self._parent_canvas.configure(yscrollcommand=self._update_scrollbar)
        self._parent_frame.bind('<Unmap>',lambda e:self.cancel_scroll(),add=True)
        self._scrollbar._canvas.bind('<ButtonPress-1>',lambda e:self.cancel_scroll(),add='+')
        self._scrollbar._canvas.bind('<MouseWheel>',self._scrollbar_wheel)
    def _update_scroll_region(self,event):
        size=(event.width,event.height)
        if size!=self._content_size:
            self._content_size=size
            self._parent_canvas.configure(scrollregion=self._parent_canvas.bbox('all'))
    def _update_scrollbar(self,start,end):
        bounds=(float(start),float(end))
        if bounds!=self._scrollbar_range:
            self._scrollbar_range=bounds
            self._scrollbar.set(*bounds)
    def bind_all(self,sequence=None,func=None,add=None):
        identity=super().bind_all(sequence,func,add)
        if func is not None:self._owned_bindings.append((sequence,identity))
        return identity
    def cancel_scroll(self):
        if self._scroll_timer is not None:
            try:self.after_cancel(self._scroll_timer)
            except tk.TclError:pass
        self._scroll_timer=None;self._target_px=None;self._last_direction=0
        self._position_px=None;self._rendered_px=None;self._segments.clear()
    def _limits(self):
        raw=self._parent_canvas.cget('scrollregion')
        if not raw:return 0.,0.
        region=[float(v) for v in self.tk.splitlist(raw)]
        total=max(0.,region[3]-region[1])
        return total,max(0.,total-self._parent_canvas.winfo_height())
    def _mouse_wheel_all(self,event):
        if self._scroll_destroyed:return
        try:valid=self._check_if_valid_scroll(event.widget)
        except (AttributeError,tk.TclError):return
        if not valid:return
        if self._shift_pressed:return super()._mouse_wheel_all(event)
        delta=getattr(event,'delta',0)
        if getattr(event,'num',None) in (4,5):delta=120 if event.num==4 else -120
        platform='win32' if getattr(event,'num',None) in (4,5) else sys.platform
        self.scroll_pixels(wheel_pixels(delta,self._get_widget_scaling(),platform),
                           animate=platform.startswith('win') and abs(delta)>=120)
        return 'break'
    def _scrollbar_wheel(self,event):
        self.scroll_pixels(wheel_pixels(event.delta,self._get_widget_scaling()),
                           animate=sys.platform.startswith('win') and abs(event.delta)>=120)
        return 'break'
    def scroll_pixels(self,amount,animate=True):
        if not amount or self._scroll_destroyed:return
        total,limit=self._limits()
        if limit<=0:self.cancel_scroll();return
        current=self._parent_canvas.yview()[0]*total
        direction=1 if amount>0 else -1
        # Reverse immediately; never finish an obsolete forward animation first.
        if (self._position_px is None or direction!=self._last_direction
                or (self._rendered_px is not None and abs(current-self._rendered_px)>1.1)):
            self.cancel_scroll()
            self._target_px=self._position_px=current;self._rendered_px=current
        self._last_direction=direction
        target=max(0.,min(limit,self._target_px+amount))
        amount=target-self._target_px;self._target_px=target
        if animate and amount:
            now=time.monotonic()
            self._segments.append([now-self._wheel_lead,amount,0.])
        else:
            # Precision wheels already supply small increments; do not delay them.
            self._position_px+=amount
        self._advance_scroll()
    def _advance_scroll(self):
        if self._scroll_destroyed or self._position_px is None:return
        total,limit=self._limits()
        if limit<=0:self.cancel_scroll();return
        current=self._parent_canvas.yview()[0]*total
        if self._rendered_px is not None and abs(current-self._rendered_px)>1.1:
            self.cancel_scroll();return
        now=time.monotonic();pending=[]
        for start,amount,previous in self._segments:
            fraction=max(previous,min(1.,(now-start)/self._wheel_duration))
            self._position_px+=amount*(fraction-previous)
            if fraction<1.:pending.append([start,amount,fraction])
        self._segments=pending
        self._target_px=max(0.,min(limit,self._target_px))
        self._position_px=max(0.,min(limit,self._position_px))
        if not pending:self._position_px=self._target_px
        if abs(self._position_px-current)>=.5:
            self._parent_canvas.yview_moveto(self._position_px/total)
        self._rendered_px=self._parent_canvas.yview()[0]*total
        if pending and self._scroll_timer is None:
            self._scroll_timer=self.after(self._frame_ms,self._scroll_tick)
        elif not pending and self._scroll_timer is not None:
            self.after_cancel(self._scroll_timer);self._scroll_timer=None
    def _scroll_tick(self):
        self._scroll_timer=None
        self._advance_scroll()
    def destroy(self):
        if self._scroll_destroyed:return
        self._scroll_destroyed=True;self.cancel_scroll()
        # Remove only this frame's global listeners, leaving other scrolling widgets intact.
        for sequence,identity in self._owned_bindings:
            try:self._root()._unbind(('bind','all',sequence),identity)
            except tk.TclError:pass
        self._owned_bindings.clear()
        super().destroy()
