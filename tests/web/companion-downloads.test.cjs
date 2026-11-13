const {test} = require('node:test');
const assert = require('node:assert/strict');
const {detectOS, releaseAssets, mount} = require('../../apps/web/companion-downloads.js');
test('platform detection never treats unknown/mobile systems as Linux', () => {
  for (const [platform, expected] of [['Win32','windows'],['MacIntel','macos'],['Linux x86_64','linux'],['','unknown']]) assert.equal(detectOS({platform}), expected);
  assert.equal(detectOS({platform:'Linux',userAgent:'Android'}), 'unknown');
  assert.equal(detectOS({platform:'MacIntel',maxTouchPoints:5}), 'unknown');
});
test('only published assets at exact versioned URLs become links', () => {
  const repo = 'owner/repo', tag = 'v0.2.0';
  const name = 'DrugDiscoveryAgent-Companion-macos-arm64.zip';
  const url = `https://github.com/${repo}/releases/download/${tag}/${name}`;
  const release = {tag_name:tag,draft:false,assets:[{name,state:'uploaded',size:100,browser_download_url:url}]};
  assert.deepEqual(releaseAssets(release,repo,tag), {'macos-arm64':{url,checksum:null}});
  assert.deepEqual(releaseAssets({...release,draft:true},repo,tag), {});
  assert.deepEqual(releaseAssets(release,repo,'v0.3.0'), {});
  release.assets[0].browser_download_url = 'https://untrusted.example/file';
  assert.deepEqual(releaseAssets(release,repo,tag), {});
});

function dom() {
  const elements = new Map();
  const element = () => ({value:'',children:[],hidden:false,append(child){this.children.push(child)},removeAttribute(key){delete this[key]}});
  return {querySelector(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element};
}
test('Mac UI offers both processors and never chooses one from MacIntel', async () => {
  const document = dom();
  const name = 'DrugDiscoveryAgent-Companion-macos-arm64.zip';
  const url = `https://github.com/owner/repo/releases/download/v0.1.1/${name}`;
  await mount({repository:'owner/repo',tag:'v0.1.1'},document,{platform:'MacIntel'},async (_,options) => {
    assert.equal(options.credentials,'omit');
    return {ok:true,json:async()=>({tag_name:'v0.1.1',assets:[{name,browser_download_url:url,size:10,state:'uploaded'}]})};
  });
  const select = document.querySelector('#companion-platform'), link = document.querySelector('#download-companion');
  assert.equal(select.value,'');
  assert.equal(link.hidden,true);
  assert.ok(select.children.some(item=>item.value==='macos-arm64'));
  assert.ok(select.children.some(item=>item.value==='macos-x64'));
  select.value='macos-arm64';select.onchange();
  assert.equal(link.hidden,false);assert.equal(link.href,url);
  select.value='macos-x64';select.onchange();
  assert.equal(link.hidden,true);assert.equal(link.href,undefined);
  assert.match(document.querySelector('#download-status').textContent,/not published/);
});
test('private or unreachable releases do not enable a broken link', async () => {
  const document = dom();
  await mount({repository:'owner/repo',tag:'v0.1.1'},document,{platform:'Win32'},async()=>({ok:false,status:404}));
  const select=document.querySelector('#companion-platform');select.value='windows-x64';select.onchange();
  assert.equal(document.querySelector('#download-companion').hidden,true);
  assert.match(document.querySelector('#download-status').textContent,/requires repository access/);
});
