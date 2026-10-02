// Isolated real browser rendering. Never connects to a user's browser profile.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('C:/Users/JIN/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const output = path.join(__dirname,process.env.QA_OUTPUT || 'settled-browser');
fs.mkdirSync(output,{recursive:true});
const steps = [];
const errors = [];

(async () => {
  const browser = await chromium.launch({headless:true, executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const context = await browser.newContext({viewport:{width:1440,height:1100},deviceScaleFactor:1});
  const page = await context.newPage();
  page.setDefaultTimeout(90000);
  page.on('pageerror', error => errors.push(String(error)));
  const consoleMessages=[];
  page.on('console',message=>consoleMessages.push({type:message.type(),text:message.text().slice(0,2000)}));
  async function settled() {
    await page.waitForTimeout(600);
    await page.getByText('Stop',{exact:true}).waitFor({state:'hidden'});
    await page.waitForTimeout(400);
  }
  async function choose(label, option) {
    const combo=page.getByRole('combobox',{name:label,exact:true});
    await combo.scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    await combo.click();
    const choice=page.getByRole('option',{name:option,exact:typeof option === 'string'});
    if (!await choice.isVisible()) await combo.press('ArrowDown');
    await choice.click({timeout:30000});
    await settled();
  }
  async function save(name, graph=true) {
    await settled();
    assert.equal(await page.locator('[data-testid="stException"]').count(),0);
    if (graph) await page.locator('[data-testid="stPlotlyChart"] canvas').first().waitFor({state:'visible'});
    const text = await page.locator('body').innerText();
    fs.writeFileSync(path.join(output,`${name}.dom.txt`),text);
    await page.screenshot({path:path.join(output,`${name}.png`),fullPage:true,animations:'disabled'});
    if (graph) await page.locator('[data-testid="stPlotlyChart"]').first().screenshot({path:path.join(output,`${name}.graph.png`),animations:'disabled'});
    const layout = await page.evaluate(() => ({viewport:[innerWidth,innerHeight],documentWidth:document.documentElement.scrollWidth,
      bodyWidth:document.body.scrollWidth,mainWidth:document.querySelector('[data-testid="stMain"]')?.getBoundingClientRect().width}));
    steps.push({name,url:page.url(),utc:new Date().toISOString(),layout,screenshot:`${name}.png`,graph:graph ? `${name}.graph.png` : null});
    fs.writeFileSync(path.join(output,'browser_steps.json'),JSON.stringify(steps,null,2));
    console.log(JSON.stringify(steps.at(-1)));
    return text;
  }
  try {
    await page.goto('http://127.0.0.1:8510/',{waitUntil:'domcontentloaded'});
    await page.getByRole('button',{name:/설계 검토$/}).waitFor();
    console.log('Loaded additive screen; selecting machining.');
    await choose('제조 공정','절삭가공');
    await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).waitFor();
    await choose('입력','절삭 검증 형상');
    await page.getByRole('combobox',{name:'절삭 형상 선택',exact:true}).waitFor();
    console.log('Loaded machining fixtures; entering tool dimensions.');
    await page.getByRole('spinbutton',{name:'엔드밀 지름 (mm)',exact:true}).fill('8');
    await page.getByRole('spinbutton',{name:'날 길이 (mm)',exact:true}).fill('10');
    await page.getByRole('spinbutton',{name:'도달 길이 · 공구 끝~홀더 (mm)',exact:true}).fill('15');
    await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();
    await settled();
    await page.getByRole('combobox',{name:'확인할 항목',exact:true}).waitFor();
    await choose('확인할 항목',/^직사각 포켓 바닥과 내부 직각/);
    const rectangleText = await save('10_rectangle_tool8_wide');
    assert.ok(rectangleText.includes('내부 직각') && rectangleText.includes('다음 행동'));

    await choose('절삭 형상 선택','둥근 포켓 · 모서리 R3 / 깊이 8 mm');
    await page.getByText('새 형상·조건에는 이전 검토 결과를 표시하지 않습니다.',{exact:true}).waitFor();
    await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();
    await settled();
    await page.getByRole('combobox',{name:'확인할 항목',exact:true}).waitFor();
    await choose('확인할 항목',/^공구축과 나란한 오목 원통면/);
    await page.getByText('오목한 부분 원통면 4개의 반경을 확인했습니다. 선택한 공구보다 작은 반경은 4개입니다.',{exact:true}).waitFor({timeout:30000});
    await save('11_rounded_tool8_wide');

    await page.getByRole('spinbutton',{name:'엔드밀 지름 (mm)',exact:true}).fill('4');
    await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();
    await settled();
    await page.getByText('오목한 부분 원통면 4개의 반경을 확인했습니다. 선택한 공구보다 작은 반경은 0개입니다.',{exact:true}).waitFor();
    const smallText = await save('12_rounded_tool4_wide');
    assert.ok(smallText.includes('공구 경로는 별도 확인이 필요합니다.'));
    await page.setViewportSize({width:780,height:1000});
    await save('13_rounded_tool4_narrow');
    await page.setViewportSize({width:1440,height:1100});

    await choose('절삭 형상 선택','단순 블록 · 포켓·구멍 없음');
    await page.getByText('새 형상·조건에는 이전 검토 결과를 표시하지 않습니다.',{exact:true}).waitFor();
    await page.getByText('선택 방향에서 가려진 표면도 확인',{exact:true}).click();
    assert.equal(await page.getByRole('checkbox',{name:'선택 방향에서 가려진 표면도 확인',exact:true}).isChecked(),true);
    await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();
    await settled();
    await page.getByRole('combobox',{name:'확인할 항목',exact:true}).waitFor();
    await choose('확인할 항목',/^선택 방향의 표면 가림/);
    await page.getByRole('combobox',{name:'표시할 표본',exact:true}).waitFor();
    const visibilityText = await save('14_block_visibility_wide');
    assert.ok(visibilityText.includes('공구 반대쪽을 향한 표본') && visibilityText.includes('공구축과 평행한 면의 표본'));
    await page.setViewportSize({width:780,height:1000});
    await save('15_block_visibility_narrow');
    await page.setViewportSize({width:1440,height:1100});

    await choose('표시할 표본','공구 반대쪽을 향한 표본');
    const filtered = await page.locator('[data-testid="stPlotlyChart"] .js-plotly-plot').first().evaluate(el=>el.data.filter(t=>t.mode==='markers').map(t=>t.name));
    assert.deepEqual(filtered,['공구 반대쪽을 향한 표본']);
    await save('15b_block_back_facing_only');

    await choose('제조 공정','적층제조');
    await page.getByRole('button',{name:/설계 검토$/}).waitFor();
    await page.getByRole('button',{name:/설계 검토$/}).click();
    await settled();
    await page.getByText('결과 보기',{exact:true}).waitFor();
    await save('16_additive_return_wide');
    const result = {status:'passed',browser:await browser.version(),headless:true,temporaryContext:true,
      realBrowserScreenshots:true,steps:steps.length,pageErrors:errors,
      limitations:['CUA browser providers unavailable; fallback used installed Edge through bundled Playwright.',
        'No physical machining or user study. Narrow/wide screenshots require visual inspection.']};
    fs.writeFileSync(path.join(output,'browser_result.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
  } catch (error) {
    fs.writeFileSync(path.join(output,'browser_failure.json'),JSON.stringify({message:String(error),stack:error.stack,steps,pageErrors:errors},null,2));
    await page.screenshot({path:path.join(output,'browser_failure.png'),fullPage:true}).catch(()=>{});
    fs.writeFileSync(path.join(output,'browser_failure.dom.txt'),await page.locator('body').innerText().catch(()=>''));
    throw error;
  } finally {fs.writeFileSync(path.join(output,'console.json'),JSON.stringify(consoleMessages,null,2));await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
