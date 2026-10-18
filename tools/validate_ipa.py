import zipfile, plistlib, struct, json, hashlib, sys
from pathlib import Path
p=Path(sys.argv[1]); report={"ipa":str(p),"sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"binaries":[]}
def ver(n): return f"{n>>16}.{(n>>8)&255}.{n&255}"
with zipfile.ZipFile(p) as z:
    bad=z.testzip(); assert bad is None,bad
    info=plistlib.loads(z.read("Payload/Minis.app/Info.plist"))
    report.update({k:info.get(k) for k in ["CFBundleIdentifier","CFBundleShortVersionString","MinimumOSVersion","CFBundleExecutable"]})
    assert info['CFBundleIdentifier'] == 'com.minisre.app', info
    assert info['CFBundleDisplayName'] == 'MinisRe', info
    assert info['CFBundleShortVersionString'] == '1.0', info
    report['CFBundleDisplayName'] = info['CFBundleDisplayName']
    assert tuple(map(int,info["MinimumOSVersion"].split("."))) <= (15,4),info
    report["plugins"]=[n for n in z.namelist() if "/PlugIns/" in n]
    for n in z.namelist():
        if n.endswith("/"):continue
        with z.open(n) as f: header=f.read(32)
        if header[:4]!=b"\xcf\xfa\xed\xfe":continue
        data=z.read(n); magic,cpu,sub,typ,ncmd,sz,flags,res=struct.unpack_from("<8I",data)
        entry={"path":n,"cpu":hex(cpu),"min_os":[],"loads":[]};off=32
        for i in range(ncmd):
            cmd,size=struct.unpack_from("<II",data,off); assert size>=8
            if cmd==0x32:
                platform,minimum,sdk,ntools=struct.unpack_from("<4I",data,off+8)
                entry["min_os"].append({"platform":platform,"minimum":ver(minimum),"sdk":ver(sdk)})
                if platform==2:entry["compatible_15_4"] = minimum<=0x000f0400
            if cmd==0x25:
                minimum,sdk=struct.unpack_from("<II",data,off+8);entry["min_os"].append({"minimum":ver(minimum),"sdk":ver(sdk)})
                entry["compatible_15_4"] = minimum<=0x000f0400
            if cmd in (0xc,0x80000018,0x8000001f):
                stroff=struct.unpack_from("<I",data,off+8)[0];name=data[off+stroff:off+size].split(b"\0")[0].decode(errors="replace")
                entry["loads"].append({"name":name,"weak":cmd==0x80000018})
            off+=size
        report["binaries"].append(entry)
    assert report["binaries"],"No ARM64 executable found"
    assert all(b.get("compatible_15_4", True) for b in report["binaries"]), "Embedded binary requires OS newer than 15.4"
    report["rootfs_entries"]=[n for n in z.namelist() if any(s in n.lower() for s in ["rootfs","alpine","fakefs"])][:30]
report["verification"]="ZIP integrity and iOS minimum metadata checked; not device tested or complete malware audit"
out=p.with_suffix(".validation.json");out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
