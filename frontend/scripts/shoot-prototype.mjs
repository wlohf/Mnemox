import { chromium } from 'playwright'
const base = process.env.URL || 'http://127.0.0.1:5190/prototype.html'
const out = 'output/prototype'
const browser = await chromium.launch()
const shots = [
  ['home-light', '?theme=light', 1440, 900],
  ['home-dark', '?theme=dark', 1440, 900],
  ['home-light-evidence', '?theme=light&evidence=1', 1440, 900],
  ['home-dark-evidence', '?theme=dark&evidence=1', 1440, 900],
  ['home-laptop', '?theme=light', 1180, 800],
  ['home-mobile', '?theme=light', 390, 844],
]
const problems = []
for (const [name, q, w, h] of shots) {
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 })
  page.on('pageerror', e => problems.push(`${name}: ${e.message}`))
  page.on('console', m => m.type() === 'error' && problems.push(`${name} console: ${m.text()}`))
  await page.goto(base + q, { waitUntil: 'networkidle' })
  await page.waitForTimeout(1400)
  await page.screenshot({ path: `${out}/${name}.png` })
  if (name === 'home-light') {
    const overflow = await page.evaluate(() => [...document.querySelectorAll('*')].filter(e => e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX === 'visible').map(e => e.className).slice(0, 10))
    if (overflow.length) problems.push('overflow: ' + overflow.join(' | '))
    await page.click('button[aria-label="查看来源 1"]')
    await page.waitForTimeout(700)
    await page.screenshot({ path: `${out}/home-cite-click.png` })
    await page.keyboard.press('Control+k')
    await page.waitForTimeout(400)
    await page.keyboard.type('复习')
    await page.screenshot({ path: `${out}/home-command.png` })
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: '确认' }).first().click()
    await page.waitForTimeout(600)
    await page.screenshot({ path: `${out}/home-draft-confirmed.png` })
  }
  await page.close()
}
await browser.close()
console.log(problems.length ? problems.join('\n') : 'no errors')
