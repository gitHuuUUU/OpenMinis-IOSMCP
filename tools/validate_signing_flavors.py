"""Read actual Mach-O code signature entitlement blobs, not source plists."""
import struct,plistlib,zipfile,sys,json

def actual(path):
 with zipfile.ZipFile(path) as z:data=z.read('Payload/Minis.app/Minis')
 off=32
 for _ in range(struct.unpack_from('<I',data,16)[0]):
  cmd,size=struct.unpack_from('<II',data,off)
  if cmd==0x1d:
   pos,count=struct.unpack_from('<II',data,off+8);sig=data[pos:pos+count]
   magic,length,blobs=struct.unpack_from('>III',sig);assert magic==0xfade0cc0
   for i in range(blobs):
    typ,blobpos=struct.unpack_from('>II',sig,12+8*i)
    if typ==5:
     _,n=struct.unpack_from('>II',sig,blobpos)
     return plistlib.loads(sig[blobpos+8:blobpos+n])
  off+=size
 raise AssertionError('No XML entitlement blob in signature')

if __name__=='__main__':
 troll=actual(sys.argv[1]);normal=actual(sys.argv[2])
 assert troll.get('platform-application') is True and troll.get('com.apple.private.security.no-sandbox') is True
 assert not troll.get('com.apple.private.security.no-container')
 assert normal=={},f'Unexpected normal payload entitlements: {list(normal)}'
 print(json.dumps({'TrollStore':troll,'Sideload':normal,'note':'Sideload payload requires user certificate/profile re-signing'},ensure_ascii=False,indent=2))
 print('Actual signing flavor verification passed')
