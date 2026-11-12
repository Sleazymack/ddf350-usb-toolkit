"""Small Tk layout primitives. No system settings or hardware access."""
import tkinter as tk
from tkinter import ttk


def wrap_to_parent(widget, parent=None, padding=16):
    """Wrap text to its actual container, not a hard-coded desktop width."""
    parent=parent or widget.master
    after_id=None
    def resize(_event=None):
        if not widget.winfo_exists():return
        width=max(40,parent.winfo_width()-padding)
        try:
            if abs(int(float(str(widget.cget('wraplength'))))-width)>2:widget.configure(wraplength=width)
        except (tk.TclError,ValueError,TypeError):pass
    binding=parent.bind('<Configure>',resize,add='+')
    def cleanup(event):
        if event.widget is widget:
            if after_id is not None:
                try:widget.after_cancel(after_id)
                except tk.TclError:pass
            try:parent.unbind('<Configure>',binding)
            except tk.TclError:pass
    widget.bind('<Destroy>',cleanup,add='+')
    after_id=widget.after_idle(resize)
    return widget


def wrap_in_control(widget):
    """For fill-width buttons: account for padding and the check indicator."""
    def resize(event=None):
        if not widget.winfo_exists():return
        actual=event.width if event is not None else widget.winfo_width()
        if actual<24:return
        extra=24
        for key in ('padx','borderwidth','highlightthickness'):
            try:extra+=2*widget.winfo_pixels(str(widget.cget(key)))
            except tk.TclError:pass
        if widget.winfo_class() in ('Radiobutton','Checkbutton'):
            import tkinter.font as font
            extra+=font.Font(root=widget,font=widget.cget('font')).metrics('linespace')
        width=max(16,actual-extra)
        if abs(int(float(str(widget.cget('wraplength'))))-width)>2:widget.configure(wraplength=width)
    widget.bind('<Configure>',resize,add='+')
    return widget


class ScrollArea(tk.Frame):
    """A vertically scrollable content frame, filling its viewport when asked.

    Its children retain natural height, so pack never reduces the last button
    to a few pixels. Wheel and keyboard focus reveal controls inside the view.
    """
    def __init__(self,master,*,bg,fill=False,width=1,height=1,**kwargs):
        super().__init__(master,bg=bg,**kwargs)
        self.fill=fill;self.fill_min_height=1;self._pending=None;self._bar_visible=False
        self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(self,bg=bg,highlightthickness=0,width=width,height=height,yscrollincrement=1,takefocus=False)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.content=tk.Frame(self.canvas,bg=bg)
        self.item=self.canvas.create_window(0,0,anchor='nw',window=self.content)
        self.canvas.bind('<Configure>',self.schedule)
        self.content.bind('<Configure>',self.schedule)
        self.top=self.winfo_toplevel()
        self.wheel_binding=self.top.bind('<MouseWheel>',self.wheel,add='+')
        self.focus_binding=self.top.bind('<FocusIn>',self.focus_changed,add='+')
        self.configure_binding=self.top.bind('<Configure>',self.child_changed,add='+')
        self.bind('<Destroy>',self.cleanup,add='+')
    def set_fill(self,value):self.fill=value;self.schedule()
    def child_changed(self,event):
        if self.owns(event.widget):self.schedule()
    def schedule(self,_event=None):
        if self._pending is None:self._pending=self.after_idle(self.resize)
    def resize(self):
        self._pending=None
        if not self.winfo_exists():return
        height=max(1,self.canvas.winfo_height())
        requested=max(height,self.fill_min_height) if self.fill else max(height,self.content.winfo_reqheight())
        show=requested>height+2
        if show!=self._bar_visible:
            self._bar_visible=show
            if show:self.bar.grid(row=0,column=1,sticky='ns')
            else:self.bar.grid_remove()
        width=max(1,self.canvas.winfo_width())
        self.canvas.itemconfigure(self.item,width=width,height=requested)
        self.canvas.configure(scrollregion=(0,0,width,requested))
        if not show:self.canvas.yview_moveto(0)
    def owns(self,widget):
        while widget is not None:
            if widget is self.content:return True
            # Let a nested scroll area own its own wheel and focus movement.
            if isinstance(widget,ScrollArea):return False
            widget=getattr(widget,'master',None)
        return False
    def wheel(self,event):
        if event.widget.winfo_class() in ('Text','TCombobox','Listbox'):return
        delta=event.delta
        if not delta:return
        candidates=[];ancestor=event.widget
        while ancestor is not None:
            if isinstance(ancestor,ScrollArea) and ancestor._bar_visible:
                start,end=ancestor.canvas.yview()
                if (delta>0 and start>0) or (delta<0 and end<1):candidates.append(ancestor)
            ancestor=getattr(ancestor,'master',None)
        if not candidates or candidates[0] is not self:return
        if delta:self.canvas.yview_scroll(-max(1,abs(delta)//120)*(1 if delta>0 else -1)*36,'units')
        return 'break'
    def reveal(self,widget):
        self.update_idletasks()
        ancestor=widget
        while ancestor is not None and ancestor is not self.content:ancestor=getattr(ancestor,'master',None)
        if ancestor is None or not self._bar_visible:return
        y=widget.winfo_rooty()-self.content.winfo_rooty();h=widget.winfo_height()
        current=self.canvas.canvasy(0);viewport=self.canvas.winfo_height()
        total=max(1,self.content.winfo_height())
        if y<current:self.canvas.yview_moveto(max(0,y-4)/total)
        elif y+h>current+viewport:self.canvas.yview_moveto(max(0,y+h-viewport+4)/total)
        self.update_idletasks()
    def focus_changed(self,event):
        if not self.owns(event.widget):return
        ancestor=event.widget
        while ancestor is not None:
            if isinstance(ancestor,ScrollArea):ancestor.reveal(event.widget)
            ancestor=getattr(ancestor,'master',None)
    def cleanup(self,event):
        if event.widget is not self:return
        if self._pending:
            try:self.after_cancel(self._pending)
            except tk.TclError:pass
        for sequence,binding in (('<MouseWheel>',self.wheel_binding),('<FocusIn>',self.focus_binding),('<Configure>',self.configure_binding)):
            try:self.top.unbind(sequence,binding)
            except tk.TclError:pass
