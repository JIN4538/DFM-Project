const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('C:/Users/JIN/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const output=path.join(__dirname,'selection-diagnosis');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext({viewport:{width:1440,height:1100}});
 const page=await context.newPage();page.setDefaultTimeout(60000);
 const logs=[],events=[];
 page.on('console',msg=>logs.push({type:msg.type(),text:msg.text().slice(0,2000)}));
 page.on('pageerror',error=>logs.push({type:'pageerror',text:String(error)}));
 async function idle(){await page.waitForTimeout(700);await page.getByText('Stop',{exact:true}).waitFor({state:'hidden'});await page.waitForTimeout(500);}
 async function choose(label,option){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name:option,exact:typeof option==='string'}).click();await idle();}
 async function record(name){
  const combo=page.getByRole('combobox',{name:'확인할 항목',exact:true});
  const widget=await combo.evaluate(el=>({id:el.id,value:el.value,form:el.closest('[data-testid="stForm"]')?.outerHTML.slice(0,2000)||null,
    parent:el.closest('[data-testid="stSelectbox"]')?.outerHTML}));
  const text=await page.locator('body').innerText();
  events.push({name,url:page.url(),utc:new Date().toISOString(),widget,body:text});
  fs.writeFileSync(path.join(output,'events.json'),JSON.stringify(events,null,2));
  fs.writeFileSync(path.join(output,'console.json'),JSON.stringify(logs,null,2));
  await page.screenshot({path:path.join(output,`${name}.png`),fullPage:true});
  console.log(JSON.stringify({name,widgetId:widget.id,inForm:!!widget.form,hasCornerReason:text.includes('선택한 공구보다 작은 반경은 4개입니다.'),hasRectangleReason:text.includes('현재 인식 범위의 직사각 포켓 바닥을 찾지 못했습니다.')}));
 }
 try{
  await page.goto('http://127.0.0.1:8510/');await page.getByRole('button',{name:/설계 검토$/}).waitFor();
  await choose('제조 공정','절삭가공');await choose('입력','절삭 검증 형상');
  await page.getByRole('spinbutton',{name:'엔드밀 지름 (mm)',exact:true}).fill('8');
  await page.getByRole('spinbutton',{name:'날 길이 (mm)',exact:true}).fill('10');
  await page.getByRole('spinbutton',{name:'도달 길이 · 공구 끝~홀더 (mm)',exact:true}).fill('15');
  await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();await idle();
  await record('01_rectangle');
  await choose('절삭 형상 선택','둥근 포켓 · 모서리 R3 / 깊이 8 mm');
  await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();await idle();
  await record('02_round_default_selection');
  await choose('확인할 항목',/^공구축과 나란한 오목 원통면/);await record('03_select_corner');
  await page.getByRole('heading',{name:'절삭가공 설계 검토',exact:true}).click();await idle();await record('04_blur');
  await page.getByRole('button',{name:'절삭 설계 검토',exact:true}).click();await idle();await record('05_resubmit');
 }finally{fs.writeFileSync(path.join(output,'console.json'),JSON.stringify(logs,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
