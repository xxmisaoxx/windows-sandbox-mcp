// Optional, guest-loopback-only browser control. No general JavaScript evaluation API.
using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

public sealed class GuestCdp:IDisposable {
    readonly JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=2097152,RecursionLimit=100};
    readonly ClientWebSocket socket=new ClientWebSocket(); int sequence=0;
    static Dictionary<string,object> Dict(object value) {return (Dictionary<string,object>)value;}
    object Call(string method,object parameters) {
        int id=++sequence;
        byte[] payload=Encoding.UTF8.GetBytes(json.Serialize(new Dictionary<string,object>{{"id",id},{"method",method},{"params",parameters}}));
        socket.SendAsync(new ArraySegment<byte>(payload),WebSocketMessageType.Text,true,CancellationToken.None).GetAwaiter().GetResult();
        for(int notifications=0;notifications<200;notifications++) {
            using(var stream=new MemoryStream()) {
                byte[] buffer=new byte[8192];WebSocketReceiveResult received;
                do {
                    received=socket.ReceiveAsync(new ArraySegment<byte>(buffer),CancellationToken.None).GetAwaiter().GetResult();
                    if(received.MessageType!=WebSocketMessageType.Text)throw new Exception("CDP connection closed or invalid message");
                    if(stream.Length+received.Count>2097152)throw new Exception("CDP response exceeds limit");
                    stream.Write(buffer,0,received.Count);
                } while(!received.EndOfMessage);
                var message=Dict(json.DeserializeObject(Encoding.UTF8.GetString(stream.ToArray())));
                if(!message.ContainsKey("id")||Convert.ToInt32(message["id"])!=id)continue;
                if(message.ContainsKey("error"))throw new Exception("CDP command failed: "+method);
                return message["result"];
            }
        }
        throw new Exception("CDP notification limit exceeded");
    }
    object Evaluate(string expression) {
        var response=Dict(Call("Runtime.evaluate",new Dictionary<string,object>{{"expression",expression},{"returnByValue",true}}));
        if(response.ContainsKey("exceptionDetails"))throw new Exception("Browser target changed or DOM operation failed");
        var remote=Dict(response["result"]);
        if(!remote.ContainsKey("value"))throw new Exception("Browser returned no bounded DOM value");
        return remote["value"];
    }
    public static Dictionary<string,object> Run(int port,string targetId,string action,string reference,string text) {
        using(var client=new GuestCdp())return client.Execute(port,targetId,action,reference,text);
    }
    Dictionary<string,object> Execute(int port,string targetId,string action,string reference,string text) {
        object[] targets;
        var http=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+port+"/json/list");
        http.Proxy=null;http.AllowAutoRedirect=false;http.Timeout=3000;http.ReadWriteTimeout=3000;
        using(var response=(HttpWebResponse)http.GetResponse()) {
            if(response.StatusCode!=HttpStatusCode.OK)throw new Exception("CDP discovery returned invalid status");
            using(var input=response.GetResponseStream())using(var discovery=new MemoryStream()) {
                byte[] buffer=new byte[8192];int count;
                while((count=input.Read(buffer,0,buffer.Length))>0) {
                    if(discovery.Length+count>1048576)throw new Exception("CDP discovery exceeds limit");
                    discovery.Write(buffer,0,count);
                }
                targets=(object[])json.DeserializeObject(Encoding.UTF8.GetString(discovery.ToArray()));
            }
        }
        Dictionary<string,object> target=null;
        foreach(object item in targets) {
            var candidate=Dict(item);
            if(Convert.ToString(candidate["type"])=="page" &&
               (String.IsNullOrEmpty(targetId)||Convert.ToString(candidate["id"])==targetId)) {target=candidate;break;}
        }
        if(target==null)throw new Exception("CDP page target not found");
        string selected=Convert.ToString(target["id"]);
        if(!System.Text.RegularExpressions.Regex.IsMatch(selected,@"^[a-zA-Z0-9_-]{1,128}$"))throw new Exception("Invalid CDP target identity");
        var uri=new Uri(Convert.ToString(target["webSocketDebuggerUrl"]));
        if(uri.Scheme!="ws"||uri.Host!="127.0.0.1"||uri.Port!=port||uri.UserInfo.Length>0||
           uri.AbsolutePath!="/devtools/page/"+selected)throw new Exception("CDP endpoint must stay on registered guest loopback");
        socket.Options.Proxy=null;
        socket.ConnectAsync(uri,CancellationToken.None).GetAwaiter().GetResult();
        object result;
        if(action=="snapshot") {
            string token=Guid.NewGuid().ToString("N");
            string script=@"(()=>{const elements=Array.from(document.querySelectorAll('button,input,textarea,select,a[href],[role],[contenteditable=true]')).filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'}).slice(0,500);window.__wsmcpSnapshot={token:TOKEN,elements};return {snapshot_id:TOKEN,coordinate_space:'viewport-css',nodes:elements.map((e,i)=>{const r=e.getBoundingClientRect();const password=e.type==='password'||/password/.test(e.autocomplete||'');return {ref:TOKEN+':'+i,tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',name:(e.getAttribute('aria-label')||e.innerText||e.placeholder||e.id||'').slice(0,256),value:password?null:String(e.value||'').slice(0,256),password,enabled:!e.disabled,bounds:{x:r.x,y:r.y,width:r.width,height:r.height}}})}})()";
            result=Evaluate(script.Replace("TOKEN",json.Serialize(token)));
        } else {
            string[] parts=(reference??"").Split(':');int index;
            if(parts.Length!=2||!System.Text.RegularExpressions.Regex.IsMatch(parts[0],"^[0-9a-f]{32}$")||
               !Int32.TryParse(parts[1],out index)||index<0||index>=500)throw new Exception("Invalid browser reference");
            string prepare=@"(()=>{const s=window.__wsmcpSnapshot;if(!s||s.token!==TOKEN)throw Error('STALE_REFERENCE');const e=s.elements[INDEX];if(!e||!e.isConnected||e.disabled)throw Error('STALE_REFERENCE');e.scrollIntoView({block:'center',inline:'center'});ACTION;const r=e.getBoundingClientRect();if(r.width<=0||r.height<=0)throw Error('TARGET_HIDDEN');return {x:r.x+r.width/2,y:r.y+r.height/2}})()";
            string focus=action=="fill"?"if(!(e.matches('input,textarea')||e.isContentEditable)||e.readOnly)throw Error('NOT_EDITABLE');e.focus();if(e.select)e.select();else{const r=document.createRange();r.selectNodeContents(e);const s=getSelection();s.removeAllRanges();s.addRange(r)}":"";
            var point=Dict(Evaluate(prepare.Replace("TOKEN",json.Serialize(parts[0])).Replace("INDEX",index.ToString()).Replace("ACTION",focus)));
            if(action=="click") {
                foreach(string kind in new[]{"mousePressed","mouseReleased"})Call("Input.dispatchMouseEvent",
                    new Dictionary<string,object>{{"type",kind},{"x",point["x"]},{"y",point["y"]},{"button","left"},{"clickCount",1}});
            } else if(action=="fill")Call("Input.insertText",new Dictionary<string,object>{{"text",text}});
            else throw new Exception("Unsupported browser action");
            result=new Dictionary<string,object>{{"applied",true}};
        }
        var output=Dict(result);output["target_id"]=selected;output["backend"]="cdp";return output;
    }
    public void Dispose(){socket.Abort();socket.Dispose();}
}
