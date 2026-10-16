// Native Windows accessibility client. Runs only in a disposable guest worker.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Accessibility;

public static class NativeAccessibility {
    [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid cls,IntPtr outer,uint context,ref Guid iid,out IntPtr obj);
    [DllImport("oleacc.dll")] static extern int AccessibleObjectFromWindow(IntPtr hwnd,uint id,ref Guid iid,[MarshalAs(UnmanagedType.Interface)] out IAccessible obj);
    [DllImport("oleacc.dll")] static extern int AccessibleChildren(IAccessible parent,int start,int count,
        [Out,MarshalAs(UnmanagedType.LPArray,ArraySubType=UnmanagedType.Struct,SizeParamIndex=2)] object[] children,out int obtained);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int OutPointer(IntPtr self,out IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int FromHandle(IntPtr self,IntPtr hwnd,out IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Navigate(IntPtr self,IntPtr element,out IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Property(IntPtr self,int id,[MarshalAs(UnmanagedType.Struct)] out object value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Service(IntPtr self,ref Guid service,ref Guid iid,out IntPtr value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int OutInt(IntPtr self,out int value);
    static T Method<T>(IntPtr obj,int slot) where T:class {
        IntPtr address=Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*IntPtr.Size);
        return (T)(object)Marshal.GetDelegateForFunctionPointer(address,typeof(T));
    }
    static object Prop(IntPtr element,int id) {
        object value; return Method<Property>(element,10)(element,id,out value)>=0?value:null;
    }
    static string Str(object value,int limit) {
        string text=value as string; if(text==null)return "";
        return text.Length>limit?text.Substring(0,limit):text;
    }
    static bool Bool(object value) { return value is bool && (bool)value; }
    static Dictionary<string,object> Bounds(double x,double y,double w,double h) {
        if(Double.IsNaN(x)||Double.IsInfinity(x)||Double.IsNaN(y)||Double.IsInfinity(y)||
           Double.IsNaN(w)||Double.IsInfinity(w)||Double.IsNaN(h)||Double.IsInfinity(h)) x=y=w=h=0;
        return new Dictionary<string,object>{{"x",x},{"y",y},{"width",w},{"height",h}};
    }
    static string ControlType(int id) {
        string[] types={"Button","Calendar","CheckBox","ComboBox","Edit","Hyperlink","Image","ListItem","List",
            "Menu","MenuBar","MenuItem","ProgressBar","RadioButton","ScrollBar","Slider","Spinner","StatusBar",
            "Tab","TabItem","Text","ToolBar","ToolTip","Tree","TreeItem","Custom","Group","Thumb","DataGrid",
            "DataItem","Document","SplitButton","Window","Pane","Header","HeaderItem","Table","TitleBar","Separator"};
        return "ControlType."+(id>=50000 && id<50000+types.Length?types[id-50000]:"Custom");
    }
    public static Dictionary<string,object> Uia(long hwnd,int maximum,int milliseconds,string view) {
        var watch=Stopwatch.StartNew(); var nodes=new List<Dictionary<string,object>>();
        var queue=new Queue<Tuple<IntPtr,int,int>>(); IntPtr automation=IntPtr.Zero,walker=IntPtr.Zero,root=IntPtr.Zero;
        int chars=131072; bool truncated=false;
        try {
            Guid cls=new Guid("ff48dba4-60ef-4201-aa87-54103eef594e"),iid=new Guid("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee");
            Marshal.ThrowExceptionForHR(CoCreateInstance(ref cls,IntPtr.Zero,1,ref iid,out automation));
            Marshal.ThrowExceptionForHR(Method<FromHandle>(automation,6)(automation,new IntPtr(hwnd),out root));
            Marshal.ThrowExceptionForHR(Method<OutPointer>(automation,view=="raw"?16:view=="content"?15:14)(automation,out walker));
            queue.Enqueue(Tuple.Create(root,-1,0)); root=IntPtr.Zero;
            while(queue.Count>0 && nodes.Count<maximum && watch.ElapsedMilliseconds<milliseconds) {
                var entry=queue.Dequeue(); IntPtr element=entry.Item1;
                try {
                    bool password=Bool(Prop(element,30019)); object control=Prop(element,30003);
                    double[] rect=Prop(element,30001) as double[];
                    string name=password?"":Str(Prop(element,30005),Math.Min(1024,chars)); chars-=name.Length;
                    string value=password?null:Str(Prop(element,30045),Math.Min(16384,chars)); if(value!=null)chars-=value.Length;
                    var patterns=new List<string>();
                    if(Bool(Prop(element,30031)))patterns.Add("Invoke");
                    if(Bool(Prop(element,30043)))patterns.Add("Value");
                    var node=new Dictionary<string,object>{{"index",nodes.Count},{"parent",entry.Item2},
                        {"name",name},{"automation_id",Str(Prop(element,30011),256)},
                        {"type",ControlType(control is int?(int)control:0)},{"enabled",Bool(Prop(element,30010))},
                        {"password",password},{"value",value},{"backend","uia3"},{"patterns",patterns},
                        {"bounds",rect!=null&&rect.Length==4?Bounds(rect[0],rect[1],rect[2],rect[3]):Bounds(0,0,0,0)}};
                    int parent=nodes.Count; nodes.Add(node);
                    if(entry.Item3>=64){truncated=true;continue;}
                    IntPtr child;
                    int hr=Method<Navigate>(walker,4)(walker,element,out child);
                    while(hr>=0 && child!=IntPtr.Zero) {
                        if(queue.Count+nodes.Count>=maximum || watch.ElapsedMilliseconds>=milliseconds) {
                            Marshal.Release(child);truncated=true;break;
                        }
                        IntPtr next; hr=Method<Navigate>(walker,6)(walker,child,out next);
                        queue.Enqueue(Tuple.Create(child,parent,entry.Item3+1)); child=next;
                    }
                } catch(COMException) { } finally {Marshal.Release(element);}
            }
            truncated=truncated||queue.Count>0||watch.ElapsedMilliseconds>=milliseconds;
            return new Dictionary<string,object>{{"hwnd",hwnd},{"nodes",nodes},{"backend","uia3"},
                {"view",view},{"truncated",truncated},{"duration_ms",watch.ElapsedMilliseconds}};
        } finally {
            while(queue.Count>0)Marshal.Release(queue.Dequeue().Item1);
            foreach(IntPtr p in new[]{root,walker,automation})if(p!=IntPtr.Zero)Marshal.Release(p);
        }
    }
    static int Ia2Role(IAccessible accessible) {
        IntPtr unknown=Marshal.GetIUnknownForObject(accessible),provider=IntPtr.Zero,ia2=IntPtr.Zero;
        try {
            Guid serviceIid=new Guid("6d5140c1-7436-11ce-8034-00aa006009fa");
            if(Marshal.QueryInterface(unknown,ref serviceIid,out provider)<0)return 0;
            Guid service=new Guid("618736e0-3c3d-11cf-810c-00aa00389b71"),iid=new Guid("e89f726e-c4f4-4c19-bb19-b647d7fa8478");
            if(Method<Service>(provider,3)(provider,ref service,ref iid,out ia2)<0 || ia2==IntPtr.Zero)return 0;
            int role; return Method<OutInt>(ia2,31)(ia2,out role)>=0?role:0;
        } finally {foreach(IntPtr p in new[]{ia2,provider,unknown})if(p!=IntPtr.Zero)Marshal.Release(p);}
    }
    static string MsaaType(int role) {
        switch(role) {
            case 43:return "ControlType.Button";case 42:return "ControlType.Edit";case 41:return "ControlType.Text";
            case 15:return "ControlType.Document";case 30:return "ControlType.Hyperlink";
            case 44:return "ControlType.CheckBox";case 45:return "ControlType.RadioButton";
            case 46:return "ControlType.ComboBox";case 34:return "ControlType.ListItem";
            case 60:return "ControlType.TabItem";default:return "ControlType.Pane";
        }
    }
    public static Dictionary<string,object> Ia2(long hwnd,int maximum,int milliseconds) {
        var watch=Stopwatch.StartNew(); var nodes=new List<Dictionary<string,object>>();
        var queue=new Queue<Tuple<IAccessible,int,int,int>>(); var seen=new HashSet<string>();
        Guid iid=new Guid("618736e0-3c3d-11cf-810c-00aa00389b71");IAccessible root;
        Marshal.ThrowExceptionForHR(AccessibleObjectFromWindow(new IntPtr(hwnd),0xfffffffc,ref iid,out root));
        queue.Enqueue(Tuple.Create(root,0,-1,0)); bool truncated=false;int chars=131072;
        while(queue.Count>0 && nodes.Count<maximum && watch.ElapsedMilliseconds<milliseconds) {
            var item=queue.Dequeue();IAccessible acc=item.Item1;object child=item.Item2;
            IntPtr identity=Marshal.GetIUnknownForObject(acc);string key=identity.ToString()+":"+item.Item2;Marshal.Release(identity);
            if(!seen.Add(key))continue;
            try {
                int state=Convert.ToInt32(acc.get_accState(child)),role=Convert.ToInt32(acc.get_accRole(child));
                bool password=(state&0x20000000)!=0;int x,y,w,h;acc.accLocation(out x,out y,out w,out h,child);
                string name=password?"":Str(acc.get_accName(child),Math.Min(1024,chars));chars-=name.Length;
                string value=null;
                if(!password)try{value=Str(acc.get_accValue(child),Math.Min(16384,chars));chars-=value.Length;}catch(COMException){}
                int extended=item.Item2==0?Ia2Role(acc):0;
                string action="";try{action=Str(acc.get_accDefaultAction(child),128);}catch(COMException){}
                int index=nodes.Count;
                nodes.Add(new Dictionary<string,object>{{"index",index},{"parent",item.Item3},{"name",name},
                    {"automation_id",""},{"type",MsaaType(role)},{"enabled",(state&1)==0},{"password",password},
                    {"value",value},{"backend","ia2"},{"ia2_role",extended},{"role",role},
                    {"patterns",action.Length>0?new[]{"DefaultAction"}:new string[0]},{"bounds",Bounds(x,y,w,h)}});
                if(item.Item2!=0)continue;
                if(item.Item4>=64){truncated=true;continue;}
                int count=Math.Min(acc.accChildCount,maximum);
                for(int start=0;start<count;start+=32) {
                    int capacity=Math.Min(32,count-start),obtained;object[] children=new object[capacity];
                    if(AccessibleChildren(acc,start,capacity,children,out obtained)<0)break;
                    for(int n=0;n<obtained;n++) {
                        if(queue.Count+nodes.Count>=maximum||watch.ElapsedMilliseconds>=milliseconds){truncated=true;break;}
                        IAccessible next=children[n] as IAccessible;
                        if(next!=null)queue.Enqueue(Tuple.Create(next,0,index,item.Item4+1));
                        else if(children[n] is int) {
                            int id=(int)children[n];
                            try{next=acc.get_accChild(id) as IAccessible;}catch(COMException){}
                            queue.Enqueue(Tuple.Create(next??acc,next==null?id:0,index,item.Item4+1));
                        }
                    }
                    if(truncated)break;
                }
            } catch(COMException) { } catch(InvalidCastException) { }
        }
        return new Dictionary<string,object>{{"hwnd",hwnd},{"nodes",nodes},{"backend","ia2"},
            {"view","raw"},{"truncated",truncated||queue.Count>0||watch.ElapsedMilliseconds>=milliseconds},
            {"duration_ms",watch.ElapsedMilliseconds}};
    }
    public static string Quote(string value) {
        if(value==null||value.IndexOf('\0')>=0)throw new ArgumentException("Invalid argument");
        var result=new System.Text.StringBuilder("\"");int slashes=0;
        foreach(char c in value) {
            if(c=='\\'){slashes++;continue;}
            if(c=='\"'){result.Append('\\',slashes*2+1);result.Append(c);slashes=0;continue;}
            result.Append('\\',slashes);slashes=0;result.Append(c);
        }
        result.Append('\\',slashes*2);return result.Append('"').ToString();
    }
}
