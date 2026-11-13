(function (root) {
  'use strict';
  const targets = Object.freeze({
    'windows-x64': 'Windows x64', 'macos-arm64': 'macOS Apple Silicon',
    'macos-x64': 'macOS Intel', 'linux-x64': 'Linux x64',
  });
  function detectOS(nav) {
    const value = ((nav.userAgentData && nav.userAgentData.platform) || nav.platform || '').toLowerCase();
    if (/android|iphone|ipad/.test((nav.userAgent || '').toLowerCase()) || (value.includes('mac') && nav.maxTouchPoints > 1)) return 'unknown';
    if (value.includes('win')) return 'windows';
    if (value.includes('mac')) return 'macos';
    if (value.includes('linux')) return 'linux';
    return 'unknown';
  }
  function releaseAssets(release, repository, tag) {
    const result = {};
    if (!/^v\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(tag) || release.draft || release.tag_name !== tag) return result;
    for (const target of Object.keys(targets)) {
      const name = `DrugDiscoveryAgent-Companion-${target}${target.startsWith('linux') ? '.tar.gz' : '.zip'}`;
      const url = `https://github.com/${repository}/releases/download/${tag}/${name}`;
      const asset = (release.assets || []).find(item => item.name === name && item.state === 'uploaded' && item.size > 0 && item.browser_download_url === url);
      if (asset) result[target] = {url, checksum: (release.assets || []).some(item => item.name === name + '.sha256' && item.state === 'uploaded' && item.size > 0 && item.browser_download_url === url + '.sha256') ? url + '.sha256' : null};
    }
    return result;
  }
  async function mount(config, document, nav, fetcher) {
    const select = document.querySelector('#companion-platform');
    const link = document.querySelector('#download-companion');
    const status = document.querySelector('#download-status');
    const steps = document.querySelector('#download-steps');
    const checksum = document.querySelector('#download-checksum');
    const os = detectOS(nav);
    let assets = {}, failure = '', checked = false;
    const placeholder = document.createElement('option');
    placeholder.value = ''; placeholder.textContent = os === 'macos' ? 'Choose your Mac processor' : 'Choose your system and processor';
    select.append(placeholder);
    for (const [target, label] of Object.entries(targets)) {
      const option = document.createElement('option'); option.value = target; option.textContent = label;
      select.append(option);
    }
    // A user agent does not reliably reveal CPU architecture, including Rosetta.
    // Suggest only an OS; the user explicitly chooses the processor.
    function render() {
      const target = select.value, asset = assets[target];
      link.hidden = !asset; link.removeAttribute('href');
      checksum.hidden = !asset?.checksum; checksum.removeAttribute('href');
      if (asset) { link.href = asset.url; link.textContent = `Download ${targets[target]}`; if (asset.checksum) checksum.href = asset.checksum; }
      status.textContent = failure || (!target ? `Detected ${os === 'unknown' ? 'an unrecognized system' : os}. Choose the matching processor; no build is selected automatically.` : asset ? `Release ${config.tag}. Verify the SHA-256 checksum before opening.` : checked ? `${targets[target]} is not published in release ${config.tag}.` : 'Checking published release assets…');
      steps.textContent = target.startsWith('macos') ? 'Apple menu → About This Mac identifies Apple Silicon or Intel. Extract the ZIP, move the app to Applications, open it, then Connect companion and approve this exact website. Use a signed, notarized release; do not disable Gatekeeper.' : target.startsWith('windows') ? 'Extract the whole ZIP, open DrugDiscoveryAgent-Companion.exe, and leave it running. Click Connect companion and approve this exact website. Check the publisher if Windows displays a trust warning.' : target.startsWith('linux') ? 'Extract the archive and run ./DrugDiscoveryAgent-Companion from its folder. Leave it running, click Connect companion, and approve this exact website.' : 'No Python installation or repository checkout is required. Windows and Linux downloads require an x64 processor.';
    }
    select.onchange = render;
    render();
    try {
      if (!/^[\w.-]+\/[\w.-]+$/.test(config.repository) || !/^v\d+\.\d+\.\d+(?:-[\w.-]+)?$/.test(config.tag)) throw new Error('No release is configured.');
      const response = await fetcher(`https://api.github.com/repos/${config.repository}/releases/tags/${config.tag}`, {credentials: 'omit', referrerPolicy: 'no-referrer', signal: AbortSignal.timeout(10000)});
      if (!response.ok) throw new Error(response.status === 404 ? 'This release is unavailable or requires repository access.' : `Release lookup failed (HTTP ${response.status}).`);
      assets = releaseAssets(await response.json(), config.repository, config.tag);
    } catch (error) { failure = `${error.message} Downloads cannot be verified. Retry when GitHub is reachable; no incompatible fallback is offered.`; }
    checked = true;
    render();
  }
  const api = {detectOS, releaseAssets, mount};
  if (typeof module !== 'undefined') module.exports = api;
  else root.CompanionDownloads = api;
})(globalThis);
