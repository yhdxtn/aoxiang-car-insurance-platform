#!/usr/bin/env node
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const assert = require('node:assert/strict')
const root = path.resolve(__dirname, '..')
const app = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'))
const errors = [],
  files = []
function walk(dir) {
  for (const item of fs.readdirSync(dir, { withFileTypes: true })) {
    if (item.name === 'preview') continue
    const file = path.join(dir, item.name)
    if (item.isDirectory()) walk(file)
    else files.push(file)
  }
}
walk(root)
for (const file of files) {
  try {
    if (file.endsWith('.json')) JSON.parse(fs.readFileSync(file, 'utf8'))
    if (file.endsWith('.js'))
      new vm.Script(fs.readFileSync(file, 'utf8'), { filename: file })
  } catch (error) {
    errors.push(error.message)
  }
}
for (const page of app.pages) {
  for (const ext of ['js', 'json', 'wxml', 'wxss'])
    if (!fs.existsSync(path.join(root, page + '.' + ext)))
      errors.push('Missing page file: ' + page + '.' + ext)
  const source = fs.readFileSync(path.join(root, page + '.js'), 'utf8')
  const wxml = fs.readFileSync(path.join(root, page + '.wxml'), 'utf8')
  for (const match of wxml.matchAll(
    /(?:bind|catch)(?:tap|input|change|confirm|agreeprivacyauthorization)="([\w]+)"/g,
  )) {
    if (!new RegExp('\\b' + match[1] + '\\s*\\(').test(source))
      errors.push(page + ' has missing handler ' + match[1])
  }
  const allowed = new Set([
    'view',
    'text',
    'button',
    'input',
    'textarea',
    'image',
    'scroll-view',
    'picker',
    'block',
    'progress',
    'assistant-avatar',
  ])
  for (const match of wxml.matchAll(/<\/?([a-zA-Z][\w-]*)/g))
    if (!allowed.has(match[1]))
      errors.push('Unsupported WXML tag ' + match[1] + ' in ' + page)
  const stack = []
  for (const match of wxml.matchAll(
    /<(\/?)([a-zA-Z][\w-]*)(?:[^"'>]|"[^"]*"|'[^']*')*>/g,
  )) {
    if (match[1]) {
      const open = stack.pop()
      if (open !== match[2])
        errors.push(
          'Tag imbalance in ' +
            page +
            ': expected ' +
            open +
            ', got ' +
            match[2],
        )
    } else if (!match[0].endsWith('/>')) stack.push(match[2])
  }
  if (stack.length)
    errors.push('Unclosed tags in ' + page + ': ' + stack.join(', '))
}
for (const item of app.tabBar.list)
  assert(app.pages.includes(item.pagePath), 'Unregistered tab page')
for (const item of app.tabBar.list) {
  for (const key of ['iconPath', 'selectedIconPath'])
    if (!fs.existsSync(path.join(root, item[key]))) errors.push('Missing tab icon ' + item[key])
}
for (const [name, component] of Object.entries(app.usingComponents)) {
  for (const ext of ['js', 'json', 'wxml', 'wxss'])
    if (!fs.existsSync(path.join(root, component + '.' + ext)))
      errors.push('Missing component ' + name + '.' + ext)
}
if (errors.length) {
  console.error(errors.join('\n'))
  process.exit(1)
}
console.log(
  'PASS: ' +
    files.length +
    ' source files checked; ' +
    app.pages.length +
    ' pages, all JSON/JS syntax, WXML tags, handlers, components and tab routes valid.',
)
