const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('C:/Users/JIN/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:1100},deviceScaleFactor:1});
    const page = await context.newPage();
    await page.goto('http://127.0.0.1:8510/', {waitUntil:'domcontentloaded'});
    await page.getByRole('combobox', {name:'제조 공정',exact:true}).waitFor({timeout:90000});
    console.log(await page.locator('body').innerText());
    await page.screenshot({path:path.join(__dirname,'00_initial_wide.png'),fullPage:false});
    fs.writeFileSync(path.join(__dirname,'00_initial_dom.txt'),await page.locator('body').innerText());
    console.log(JSON.stringify({browser:await browser.version(),headless:true,temporary_context:true,screenshot:'00_initial_wide.png'}));
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
