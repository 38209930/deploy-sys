#!/usr/bin/env node
'use strict'
// 复用项目原有配置在进程内认证；从不打印配置、SDK响应或异常对象。
const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const Module = require('module')
const { execFileSync } = require('child_process')
const repo = '/Volumes/SSD/work/ddmp/prod/yangu-prod/yangu-manage'
const domain = 'https://manage.svision100.com'
const root = path.resolve(__dirname, '..')
const action = process.argv[2] || 'status'
const sha = b => crypto.createHash('sha256').update(b).digest('hex')
const git = (...args) => execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8' }).trim()
const publicIndex = (suffix = '/index.html?release-check=' + Date.now()) => execFileSync('curl', ['--fail', '--silent', '--show-error', '--max-time', '20', domain + suffix], { maxBuffer: 1024 * 1024 })
function verifyPublic(expected) {
  for (const suffix of ['/', '/index.html', '/index.html?release-check=' + Date.now()])
    if (sha(publicIndex(suffix)) !== expected) throw new Error('PublicIndexMismatch')
}
function config() {
  let captured
  const filename = path.join(repo, 'config/deploy.js')
  const m = new Module(filename, module)
  m.filename = filename
  m.paths = Module._nodeModulePaths(path.dirname(filename))
  m.require = function (name) {
    if (name === 'ali-oss-deploy') return value => { captured = value }
    return Module.prototype.require.call(this, name)
  }
  m.load(filename)
  if (!captured || captured.ossConfig.region !== 'oss-cn-beijing' ||
      captured.bucket.prod.name !== 'gongkanyiyanmanage' || captured.bucket.prod.projectPath ||
      captured.bucket.prod.refreshPath.replace(/\/$/, '') !== domain) throw new Error('TargetMismatch')
  return captured
}
function files(dir, prefix = '') {
  return fs.readdirSync(dir).sort().flatMap(name => {
    const key = prefix + name
    const stat = fs.lstatSync(path.join(dir, name))
    if (stat.isSymbolicLink()) throw new Error('SymlinkRejected')
    return stat.isDirectory() ? files(path.join(dir, name), key + '/') : [key]
  })
}
async function main() {
  if (!['status', 'deploy', 'rollback'].includes(action)) throw new Error('InvalidAction')
  const cfg = config()
  const OSS = require(path.join(repo, 'node_modules/ali-oss'))
  const client = new OSS(Object.assign({}, cfg.ossConfig, { bucket: 'gongkanyiyanmanage', timeout: 30000 }))
  const current = await client.get('index.html')
  console.log('target=oss://gongkanyiyanmanage/ domain=' + domain + ' index_sha256=' + sha(current.content))
  if (action === 'status') {
    verifyPublic(sha(current.content))
    console.log('public_index_verified')
    return
  }
  if (process.env.YANGU_OSS_CONFIRM !== 'yes') throw new Error('ConfirmationRequired')
  let backup, manifest
  if (action === 'deploy') {
    if (git('branch', '--show-current') !== 'release' || git('status', '--porcelain')) throw new Error('ReleaseBranchMustBeClean')
    const commit = git('rev-parse', 'HEAD')
    if (git('rev-parse', 'origin/release') !== commit) throw new Error('ReleaseNotPushed')
    verifyPublic(sha(current.content))
    const dist = path.join(repo, 'dist')
    const entries = files(dist)
    if (!entries.includes('index.html')) throw new Error('MissingBuild')
    const app = entries.filter(x => /^js\/app\..+\.js$/.test(x)).map(x => fs.readFileSync(path.join(dist, x), 'utf8')).join('')
    if (!app.includes('https://rsapi.svision100.com') || app.includes('https://rsapi-test.svision100.com')) throw new Error('ApiTargetMismatch')
    backup = path.join(root, 'data/oss-backups/yangu-manage', new Date().toISOString().replace(/[:.]/g, '-') + '-' + commit.slice(0, 8))
    fs.mkdirSync(backup, { recursive: true, mode: 0o700 })
    manifest = { target: 'gongkanyiyanmanage', domain, commit, oldIndexSha256: sha(current.content), entries: [] }
    // 所有待覆盖的固定文件都先备份；hash资源保留旧版本，无需复制整个桶。
    for (const key of entries.filter(x => !/\.[0-9a-f]{8,}\./i.test(x))) {
      let previous
      try { previous = await client.get(key) } catch (e) { if (e.code !== 'NoSuchKey') throw e }
      const item = { key, existed: !!previous }
      if (previous) {
        const local = path.join(backup, 'objects', key)
        fs.mkdirSync(path.dirname(local), { recursive: true, mode: 0o700 })
        fs.writeFileSync(local, previous.content, { mode: 0o600 })
        item.sha256 = sha(previous.content)
        item.headers = {}
        for (const h of ['content-type', 'cache-control', 'content-encoding'])
          if (previous.res.headers[h]) item.headers[h] = previous.res.headers[h]
      }
      manifest.entries.push(item)
    }
    if (!manifest.entries.some(x => x.key === 'index.html' && x.existed)) throw new Error('MissingIndexBackup')
    fs.writeFileSync(path.join(backup, 'manifest.json'), JSON.stringify(manifest, null, 2), { mode: 0o600 })
    console.log('backup=' + backup + ' commit=' + commit + ' files=' + entries.length)
    for (const key of entries.filter(x => x !== 'index.html')) await client.put(key, path.join(dist, key))
    await client.put('index.html', path.join(dist, 'index.html'), { headers: { 'Cache-Control': 'no-cache' } })
    manifest.newIndexSha256 = sha(fs.readFileSync(path.join(dist, 'index.html')))
    fs.writeFileSync(path.join(backup, 'manifest.json'), JSON.stringify(manifest, null, 2), { mode: 0o600 })
  } else {
    backup = path.resolve(process.argv[3] || '')
    if (!backup.startsWith(path.join(root, 'data/oss-backups/yangu-manage') + path.sep)) throw new Error('InvalidBackup')
    manifest = JSON.parse(fs.readFileSync(path.join(backup, 'manifest.json')))
    if (manifest.target !== 'gongkanyiyanmanage' || manifest.domain !== domain) throw new Error('BackupTargetMismatch')
    for (const item of manifest.entries.filter(x => x.existed).sort((a, b) => (a.key === 'index.html') - (b.key === 'index.html'))) {
      const local = path.join(backup, 'objects', item.key)
      if (sha(fs.readFileSync(local)) !== item.sha256) throw new Error('BackupHashMismatch')
      await client.put(item.key, local, { headers: item.headers })
    }
  }
  const expected = action === 'deploy' ? manifest.newIndexSha256 : manifest.oldIndexSha256
  if (sha((await client.get('index.html')).content) !== expected) throw new Error('OriginVerifyFailed')
  // 该域名直接 CNAME 到 OSS，无 CDN；核验根路径与首页即可确认公网生效。
  verifyPublic(expected)
  console.log(action + '_verified index_sha256=' + expected + ' backup=' + backup)
}
main().catch(error => {
  const code = String(error.code || error.message || error.name || 'UnknownError')
  console.error('yangu_manage_' + action + '_failed code=' + (/^[A-Za-z0-9_]+$/.test(code) ? code : 'OperationFailed') +
    (Number.isInteger(error.status) ? ' status=' + error.status : ''))
  process.exitCode = 1
})
