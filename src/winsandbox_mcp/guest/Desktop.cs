// Guest-only helpers. Never loaded into the host MCP process.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Win32.SafeHandles;

public static class Desktop {
    [DllImport("user32.dll")] static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] static extern int GetSystemMetrics(int n);
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool IsWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h,StringBuilder s,int n);
    [DllImport("user32.dll")] static extern int GetWindowLong(IntPtr h,int index);
    [StructLayout(LayoutKind.Sequential)] struct RECT { public int left,top,right,bottom; }
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h,out RECT rect);
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern IntPtr SendMessageTimeout(
        IntPtr h,uint msg,UIntPtr w,StringBuilder text,uint flags,uint timeout,out UIntPtr result);
    delegate bool WindowCallback(IntPtr h, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumWindows(WindowCallback cb, IntPtr p);
    [DllImport("user32.dll")] static extern bool EnumChildWindows(IntPtr parent,WindowCallback cb,IntPtr p);
    [DllImport("user32.dll", SetLastError=true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
    [StructLayout(LayoutKind.Sequential)] struct INPUT { public uint type; public InputUnion u; }
    [StructLayout(LayoutKind.Explicit)] struct InputUnion {
        [FieldOffset(0)] public MOUSEINPUT mouse;
        [FieldOffset(0)] public KEYBDINPUT key;
    }
    [StructLayout(LayoutKind.Sequential)] struct MOUSEINPUT {
        public int dx,dy; public uint mouseData, flags, time; public UIntPtr extra;
    }
    [StructLayout(LayoutKind.Sequential)] struct KEYBDINPUT {
        public ushort vk, scan; public uint flags,time; public UIntPtr extra;
    }
    static void Emit(INPUT input) {
        if(SendInput(1,new INPUT[]{input},Marshal.SizeOf(typeof(INPUT))) != 1)
            throw new Exception("SendInput failed; desktop may be unavailable or protected");
    }
    static void Key(ushort vk, ushort scan, uint flags) {
        INPUT i=new INPUT(); i.type=1; i.u.key.vk=vk; i.u.key.scan=scan; i.u.key.flags=flags; Emit(i);
    }
    public static void Focus(long hwnd) {
        if(hwnd==0) return;
        IntPtr h=new IntPtr(hwnd);
        if(!IsWindow(h)) throw new Exception("Window no longer exists");
        SetForegroundWindow(h);
        System.Threading.Thread.Sleep(100);
        if(GetForegroundWindow()!=h) throw new Exception("Could not focus requested window");
    }
    public static List<Dictionary<string,object>> Windows() {
        var result=new List<Dictionary<string,object>>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            if(IsWindowVisible(h) && result.Count<300) {
                var title=new StringBuilder(1024); GetWindowText(h,title,title.Capacity);
                uint pid; GetWindowThreadProcessId(h,out pid);
                result.Add(new Dictionary<string,object>{{"hwnd",h.ToInt64()},{"title",title.ToString()},{"pid",pid}});
            } return true;
        },IntPtr.Zero);
        return result;
    }
    public static string WindowClass(long hwnd) {
        var value=new StringBuilder(256);GetClassName(new IntPtr(hwnd),value,value.Capacity);return value.ToString();
    }
    public static byte[] Screenshot() {
        SetProcessDPIAware();
        int x=GetSystemMetrics(76), y=GetSystemMetrics(77), w=GetSystemMetrics(78), h=GetSystemMetrics(79);
        if(w<=0 || h<=0 || (long)w*h>32000000) throw new Exception("Invalid desktop dimensions");
        using(var bitmap=new Bitmap(w,h)) using(var graphics=Graphics.FromImage(bitmap)) using(var stream=new MemoryStream()) {
            graphics.CopyFromScreen(x,y,0,0,new Size(w,h)); bitmap.Save(stream,ImageFormat.Png);
            if(stream.Length>4194304) throw new Exception("Screenshot exceeds 4 MiB");
            return stream.ToArray();
        }
    }
    public static List<Dictionary<string,object>> Controls(long hwnd,int max) {
        // Classic Windows 10 edit controls can lack UIA providers in Sandbox.
        // WM_GETTEXT uses the OS-supported cross-process system-message marshalling.
        var nodes=new List<Dictionary<string,object>>();
        var clock=System.Diagnostics.Stopwatch.StartNew();
        EnumChildWindows(new IntPtr(hwnd),delegate(IntPtr h,IntPtr p) {
            if(nodes.Count>=max || clock.ElapsedMilliseconds>5000) return false;
            var name=new StringBuilder(1024); var cls=new StringBuilder(256);
            GetWindowText(h,name,name.Capacity); GetClassName(h,cls,cls.Capacity);
            string classname=cls.ToString();
            bool edit=classname.Equals("Edit",StringComparison.OrdinalIgnoreCase) || classname.StartsWith("RichEdit",StringComparison.OrdinalIgnoreCase);
            bool password=edit && (GetWindowLong(h,-16)&0x20)!=0;
            string value=null;
            if(edit && !password) {
                var text=new StringBuilder(16385); UIntPtr count;
                if(SendMessageTimeout(h,13,new UIntPtr(16385),text,2,200,out count)!=IntPtr.Zero) value=text.ToString();
            }
            RECT rect; GetWindowRect(h,out rect);
            nodes.Add(new Dictionary<string,object>{{"hwnd",h.ToInt64()},{"name",password?"":name.ToString()},
                {"class",classname},{"type",edit?"ControlType.Edit":"ControlType.Pane"},{"password",password},
                {"value",value},{"backend","win32"},{"bounds",new Dictionary<string,object>{{"x",rect.left},
                {"y",rect.top},{"width",rect.right-rect.left},{"height",rect.bottom-rect.top}}}});
            return true;
        },IntPtr.Zero);
        return nodes;
    }
    public static void Click(int x,int y,string button) {
        SetProcessDPIAware();
        int left=GetSystemMetrics(76),top=GetSystemMetrics(77),w=GetSystemMetrics(78),h=GetSystemMetrics(79);
        if(x<left || y<top || x>=left+w || y>=top+h) throw new Exception("Click outside desktop");
        if(!SetCursorPos(x,y)) throw new Exception("Cannot move pointer");
        INPUT i=new INPUT(); i.u.mouse.flags=button=="right"?8u:2u; Emit(i);
        i.u.mouse.flags=button=="right"?16u:4u; Emit(i);
    }
    public static void Text(string text) {
        if(text.Length>16384) throw new Exception("Text exceeds limit");
        foreach(char c in text) { Key(0,c,4); Key(0,c,6); }
    }
    public static void Keys(string chord) {
        var keys=new Dictionary<string,ushort>(StringComparer.OrdinalIgnoreCase) {
            {"CTRL",0x11},{"ALT",0x12},{"SHIFT",0x10},{"WIN",0x5b},{"ENTER",0x0d},{"TAB",9},
            {"ESC",0x1b},{"BACKSPACE",8},{"DELETE",0x2e},{"HOME",0x24},{"END",0x23},
            {"LEFT",0x25},{"UP",0x26},{"RIGHT",0x27},{"DOWN",0x28},{"SPACE",0x20},
            {"F4",0x73},{"F5",0x74},{"F6",0x75},{"F12",0x7b}
        };
        var codes=new List<ushort>();
        foreach(string part in chord.Split('+')) {
            ushort code;
            if(!keys.TryGetValue(part,out code)) {
                if(part.Length!=1 || !Char.IsLetterOrDigit(part[0]) || part[0]>127)
                    throw new Exception("Unsupported key in chord");
                code=(ushort)Char.ToUpperInvariant(part[0]);
            }
            codes.Add(code);
        }
        if(codes.Count<1 || codes.Count>5) throw new Exception("Invalid key chord");
        int pressed=0;
        try { foreach(ushort c in codes) { Key(c,0,0); pressed++; } }
        finally { for(int n=pressed-1;n>=0;n--) Key(codes[n],0,2); }
    }
}

public static class GuestCommand {
    [StructLayout(LayoutKind.Sequential)] struct SECURITY { public int size; public IntPtr descriptor; public int inherit; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] struct STARTUP {
        public int size; public string reserved,desktop,title; public int x,y,w,h,cx,cy,fill,flags;
        public short show,reserved2; public IntPtr extra,input,output,error;
    }
    [StructLayout(LayoutKind.Sequential)] struct PROCESS { public IntPtr process,thread; public uint pid,tid; }
    [StructLayout(LayoutKind.Sequential)] struct LIMIT {
        public long processTime,jobTime; public uint flags; public UIntPtr min,max;
        public uint active; public UIntPtr affinity; public uint priority,scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong a,b,c,d,e,f; }
    [StructLayout(LayoutKind.Sequential)] struct EXTENDED {
        public LIMIT basic; public IO io; public UIntPtr processMemory,jobMemory,peakProcess,peakJob;
    }
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool CreatePipe(out IntPtr r,out IntPtr w,ref SECURITY s,int size);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetHandleInformation(IntPtr h,uint mask,uint flags);
    [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr p,string name);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool SetInformationJobObject(IntPtr j,int c,ref EXTENDED info,int len);
    [DllImport("kernel32.dll",SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr j,IntPtr p);
    [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] static extern bool CreateProcess(
        string app,StringBuilder cmd,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr env,string dir,ref STARTUP si,out PROCESS pi);
    [DllImport("kernel32.dll")] static extern uint ResumeThread(IntPtr t);
    [DllImport("kernel32.dll")] static extern uint WaitForSingleObject(IntPtr h,uint ms);
    [DllImport("kernel32.dll")] static extern bool GetExitCodeProcess(IntPtr h,out uint code);
    [DllImport("kernel32.dll")] static extern bool TerminateProcess(IntPtr h,uint code);
    [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
    static Exception Error() { return new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error()); }
    static string Drain(IntPtr handle,int limit) {
        using(var stream=new FileStream(new SafeFileHandle(handle,true),FileAccess.Read))
        using(var reader=new StreamReader(stream,Encoding.UTF8,true,4096)) {
            var result=new StringBuilder(); char[] buffer=new char[4096]; int count;
            while((count=reader.Read(buffer,0,buffer.Length))>0) {
                int keep=Math.Min(count,limit-result.Length); if(keep>0) result.Append(buffer,0,keep);
            }
            return result.ToString();
        }
    }
    public static Dictionary<string,object> Run(string command,int timeout) {
        return Run(command,timeout,65536);
    }
    public static Dictionary<string,object> Run(string command,int timeout,int limit) {
        if(limit<1 || limit>2097152) throw new ArgumentException("Invalid output limit");
        string exe=Environment.GetFolderPath(Environment.SpecialFolder.System)+@"\WindowsPowerShell\v1.0\powershell.exe";
        string prelude="$ProgressPreference='SilentlyContinue';[Console]::OutputEncoding=New-Object Text.UTF8Encoding;$OutputEncoding=[Console]::OutputEncoding;";
        string script=Path.Combine(Path.GetTempPath(),"mcp-"+Guid.NewGuid().ToString("N")+".ps1");
        File.WriteAllText(script,prelude+command,new UTF8Encoding(true));
        var cmd=new StringBuilder("\""+exe+"\" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File \""+script+"\"");
        IntPtr job=IntPtr.Zero,stdoutR=IntPtr.Zero,stdoutW=IntPtr.Zero,stderrR=IntPtr.Zero,stderrW=IntPtr.Zero;
        PROCESS process=new PROCESS(); bool assigned=false;
        try {
            job=CreateJobObject(IntPtr.Zero,null); if(job==IntPtr.Zero) throw Error();
            EXTENDED limits=new EXTENDED(); limits.basic.flags=0x2000;
            if(!SetInformationJobObject(job,9,ref limits,Marshal.SizeOf(typeof(EXTENDED)))) throw Error();
            SECURITY security=new SECURITY(); security.size=Marshal.SizeOf(typeof(SECURITY)); security.inherit=1;
            if(!CreatePipe(out stdoutR,out stdoutW,ref security,0) || !CreatePipe(out stderrR,out stderrW,ref security,0)) throw Error();
            if(!SetHandleInformation(stdoutR,1,0) || !SetHandleInformation(stderrR,1,0)) throw Error();
            STARTUP startup=new STARTUP(); startup.size=Marshal.SizeOf(typeof(STARTUP)); startup.flags=0x101;
            startup.output=stdoutW; startup.error=stderrW;
            // Assign while suspended so children cannot escape before job assignment.
            if(!CreateProcess(exe,cmd,IntPtr.Zero,IntPtr.Zero,true,0x08000004,IntPtr.Zero,@"C:\work",ref startup,out process)) throw Error();
            if(!AssignProcessToJobObject(job,process.process)) throw Error(); assigned=true;
            CloseHandle(stdoutW);stdoutW=IntPtr.Zero; CloseHandle(stderrW);stderrW=IntPtr.Zero;
            IntPtr outHandle=stdoutR, errHandle=stderrR; stdoutR=IntPtr.Zero;stderrR=IntPtr.Zero;
            Task<string> output=Task.Factory.StartNew(()=>Drain(outHandle,limit));
            Task<string> error=Task.Factory.StartNew(()=>Drain(errHandle,limit));
            if(ResumeThread(process.thread)==0xffffffff) throw Error();
            bool timedOut=WaitForSingleObject(process.process,(uint)timeout)==258;
            uint exit; GetExitCodeProcess(process.process,out exit);
            CloseHandle(job); job=IntPtr.Zero;
            if(!Task.WaitAll(new Task[]{output,error},5000)) throw new Exception("Output drain timeout");
            return new Dictionary<string,object>{{"stdout",output.Result},{"stderr",error.Result},
                {"exit_code",timedOut?(object)null:(int)exit},{"timed_out",timedOut},
                {"output_limit_chars",limit},{"possibly_truncated",output.Result.Length==limit || error.Result.Length==limit}};
        } finally {
            if(process.process!=IntPtr.Zero && !assigned) TerminateProcess(process.process,1);
            foreach(IntPtr h in new IntPtr[]{job,process.process,process.thread,stdoutR,stdoutW,stderrR,stderrW})
                if(h!=IntPtr.Zero) CloseHandle(h);
            try { File.Delete(script); } catch(IOException) { }
        }
    }
}
