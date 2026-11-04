import os, sys, time, json, re, subprocess, shutil, base64
from pathlib import Path
import requests

REPO=os.environ["REPO"]; TOKEN=os.environ["GH_TOKEN"]; OWNER=os.environ["OWNER"].lower()
BRANCH="workspace-windows"; TITLE="[windows-executor-status]"; BOT="github-actions[bot]"
ROOT=Path(os.environ["RUNNER_TEMP"])/"windows-workspace"; WORK=ROOT/"work"; REPO_DIR=ROOT/"repo"
API="https://api.github.com/repos/"+REPO
S=requests.Session()
S.headers.update({"Authorization":"Bearer "+TOKEN,"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"})

def api(method,path,body=None,params=None):
    r=S.request(method,API+path,json=body,params=params,timeout=30)
    try: data=r.json() if r.content else None
    except ValueError: data=None
    return r.status_code,data

def git(args):
    env=os.environ.copy(); auth=base64.b64encode(("x-access-token:"+TOKEN).encode()).decode()
    env.update({"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"http.https://github.com/.extraheader","GIT_CONFIG_VALUE_0":"AUTHORIZATION: basic "+auth,"GIT_TERMINAL_PROMPT":"0"})
    return subprocess.run(["git","-C",str(REPO_DIR)]+args,env=env,capture_output=True,text=True)

def clone():
    ROOT.mkdir(parents=True,exist_ok=True)
    if (REPO_DIR/".git").exists(): return
    env=os.environ.copy(); auth=base64.b64encode(("x-access-token:"+TOKEN).encode()).decode()
    env.update({"GIT_CONFIG_COUNT":"1","GIT_CONFIG_KEY_0":"http.https://github.com/.extraheader","GIT_CONFIG_VALUE_0":"AUTHORIZATION: basic "+auth})
    q=subprocess.run(["git","ls-remote","--heads","https://github.com/"+REPO,BRANCH],env=env,capture_output=True,text=True)
    if q.stdout.strip():
        p=subprocess.run(["git","clone","--depth","1","--branch",BRANCH,"https://github.com/"+REPO,str(REPO_DIR)],env=env,capture_output=True,text=True)
        if p.returncode: raise RuntimeError(p.stderr)
    else:
        p=subprocess.run(["git","clone","--depth","1","https://github.com/"+REPO,str(REPO_DIR)],env=env,capture_output=True,text=True)
        if p.returncode: raise RuntimeError(p.stderr)
        git(["checkout","--orphan",BRANCH]); git(["rm","-rf","--ignore-unmatch","."])
        subprocess.run(["git","-C",str(REPO_DIR),"clean","-fdx"])
        git(["commit","--allow-empty","-m","Initialize Windows workspace"])
    git(["config","user.name","windows-workspace-bot"]); git(["config","user.email","windows-workspace-bot@users.noreply.github.com"])

def copy_contents(src,dst):
    dst.mkdir(parents=True,exist_ok=True)
    for p in src.iterdir():
        if p.name in {".git","node_modules","__pycache__",".venv","venv",".cache"}: continue
        t=dst/p.name
        if p.is_dir(): shutil.copytree(p,t,dirs_exist_ok=True,ignore=shutil.ignore_patterns(".git","node_modules","__pycache__",".venv","venv",".cache"))
        elif p.is_file(): shutil.copy2(p,t)

def sync():
    if not (REPO_DIR/".git").exists(): return
    for p in REPO_DIR.iterdir():
        if p.name==".git": continue
        if p.is_dir(): shutil.rmtree(p,ignore_errors=True)
        else: p.unlink(missing_ok=True)
    copy_contents(WORK,REPO_DIR); git(["add","-A"])
    if git(["diff","--cached","--quiet"]).returncode==0: return
    p=git(["commit","-m","Windows workspace sync"])
    if p.returncode: raise RuntimeError(p.stderr)
    p=git(["push","origin","HEAD:refs/heads/"+BRANCH])
    if p.returncode: raise RuntimeError(p.stderr)
    print("Synced Windows workspace",flush=True)

def status_issue():
    _,items=api("GET","/issues",params={"state":"open","per_page":100})
    for x in items or []:
        if x.get("title")==TITLE and "pull_request" not in x: return x["number"]
    st,d=api("POST","/issues",{"title":TITLE,"body":"starting"})
    if st!=201: raise RuntimeError("Cannot create status issue: "+str(d))
    return d["number"]

def heartbeat(n,state):
    api("PATCH","/issues/"+str(n),{"body":json.dumps({"state":state,"ts":int(time.time()),"os":"windows"})})

def run_ps(command,timeout):
    timeout=max(1,min(int(timeout or 120),600))
    p=subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-Command",command],cwd=str(WORK),env=os.environ.copy(),capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
    out=(p.stdout or "")+(p.stderr or "")
    if len(out)>20000: out=out[:10000]+"\n...[truncated]...\n"+out[-10000:]
    return {"ok":p.returncode==0,"exit":p.returncode,"output":out,"ms":0}

def execute(payload):
    tool=payload.get("tool"); args=payload.get("args") or {}
    if tool=="win_powershell": return run_ps(args.get("command",""),args.get("timeout",120))
    if tool=="win_get_environment":
        import ctypes
        return {"ok":True,"exit":0,"output":"OS: Windows\nUser: "+os.environ.get("USERNAME","")+"\nAdministrator: "+str(bool(ctypes.windll.shell32.IsUserAnAdmin()))+"\nWorkspace: "+str(WORK)+"\nCPU: "+str(os.cpu_count())+"\nPython: "+sys.version.split()[0]}
    return {"ok":False,"exit":1,"output":"Unknown Windows tool: "+str(tool)}

def main():
    import ctypes
    if not ctypes.windll.shell32.IsUserAnAdmin(): raise RuntimeError("Runner is not elevated as Administrator")
    WORK.mkdir(parents=True,exist_ok=True)
    if "--sync-only" in sys.argv:
        sync(); return
    clone(); copy_contents(REPO_DIR,WORK); n=status_issue(); heartbeat(n,"online")
    start=last=last_sync=last_hb=time.time(); done=set(); seen={}
    while time.time()-start<5.5*3600 and time.time()-last<45*60:
        now=time.time()
        if now-last_hb>60:
            _,d=api("GET","/issues/"+str(n)); m=re.search(r"\{[^{}]*\}",(d or {}).get("body",""))
            if m and json.loads(m.group()).get("state")=="stop": break
            heartbeat(n,"online"); last_hb=now
        if now-last_sync>120:
            try: sync()
            except Exception as e: print("sync warning:",e,flush=True)
            last_sync=now
        st,issues=api("GET","/issues",params={"labels":"chat","state":"open","per_page":50,"sort":"updated"})
        if st==200:
            for issue in issues or []:
                if "pull_request" in issue or (issue.get("user") or {}).get("login","").lower()!=OWNER: continue
                no=issue["number"]
                if seen.get(no)==issue.get("updated_at"): continue
                _,comments=api("GET","/issues/"+str(no)+"/comments",params={"per_page":100})
                for c in comments or []:
                    if (c.get("user") or {}).get("login")!=BOT: continue
                    m=re.match(r"^<!--tool-call:([0-9a-f]{6,16})-->\n(.*)$",c.get("body",""),re.S)
                    if not m or m.group(1) in done: continue
                    try: payload=json.loads(m.group(2))
                    except ValueError: continue
                    if payload.get("tool") not in {"win_powershell","win_get_environment"}: continue
                    done.add(m.group(1)); result=execute(payload)
                    api("POST","/issues/"+str(no)+"/comments",{"body":"<!--tool-result:"+m.group(1)+"-->\n"+json.dumps(result,ensure_ascii=False)})
                    last=time.time()
                seen[no]=issue.get("updated_at")
        time.sleep(3)
    try: sync()
    finally: heartbeat(n,"offline")

if __name__=="__main__": main()
