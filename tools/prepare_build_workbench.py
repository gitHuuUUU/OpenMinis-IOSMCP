"""Validate the on-demand SDK catalog; never fetch archives into the app bundle."""
import json
import pathlib
import re

bundle=pathlib.Path(__file__).resolve().parents[1]/'src/ios/BuildWorkbench.bundle'
items=json.loads((bundle/'sdk-catalog.json').read_text(encoding='utf-8'))['sdks']
assert [i['version'] for i in items]==['15.6','16.5','17.5','18.6']
for item in items:
    assert item['sdkRoot']=='iPhoneOS'+item['version']+'.sdk'
    assert item['file']==item['sdkRoot']+('.zip' if item['file'].endswith('.zip') else '.tar.xz')
    assert item['url'].startswith('https://')
    assert re.fullmatch(r'[0-9a-f]{64}',item['sha256'])
    assert isinstance(item['bytes'],int) and item['bytes']>0
    if (bundle/item['file']).exists():
        raise RuntimeError('SDK archive remains inside IPA resource bundle: '+item['file'])
print('Four pinned SDK metadata entries validated; zero SDK archives bundled')
