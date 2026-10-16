using System;
using System.Threading;
using System.Windows.Forms;

public sealed class HungProvider:Form {
    public HungProvider(){Text="Hung accessibility fixture";Width=400;Height=200;}
    protected override AccessibleObject CreateAccessibilityInstance(){return new Blocked(this);}
    sealed class Blocked:Control.ControlAccessibleObject {
        public Blocked(Control owner):base(owner){}
        public override int GetChildCount(){Thread.Sleep(60000);return 0;}
    }
    [STAThread] public static void Main(string[] args){
        if(args.Length>0){
            string[] encoded=Array.ConvertAll(args,a=>Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(a)));
            System.IO.File.WriteAllLines(@"C:\work\argv.txt",encoded);return;
        }
        Application.Run(new HungProvider());
    }
}
