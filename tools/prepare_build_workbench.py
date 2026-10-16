import pathlib,json,hashlib,subprocess
root=pathlib.Path(__file__).resolve().parents[1]/'src/ios/BuildWorkbench.bundle'
for item in json.loads((root/'sdk-catalog.json').read_text())['sdks']:
    path=root/item['file']
    if not path.exists(): subprocess.run(['curl','--fail','--location','--retry','3',item['url'],'-o',str(path)],check=True)
    assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256'],item['file']
print('Four pinned SDK archives verified for bundling')
