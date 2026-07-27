// 卢娜前端交互：头像填充、时段问候、发消息、渲染「闲聊回复」或「修复结果卡」。
const cattpl = document.getElementById('cattpl');
function catFill(el){ el.appendChild(cattpl.content.cloneNode(true)); }
document.querySelectorAll('[data-cat]').forEach(catFill);
const _probe = new Image();          // 有 assets/luna.* 就用真图，否则留内置 SVG
_probe.onload = function(){ document.body.classList.add('has-portrait'); };
_probe.src = '/portrait';

const log = () => document.getElementById('log');
function scroll(){ const l = log(); l.scrollTop = l.scrollHeight; }
function esc(s){ return (s==null?'':String(s)).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
function timeGreeting(){ const h = new Date().getHours();
  if(h<5) return '夜深了'; if(h<9) return '早上好'; if(h<12) return '上午好';
  if(h<14) return '中午好'; if(h<18) return '下午好'; if(h<23) return '晚上好'; return '夜深了'; }
function msg(who, text){
  const m = document.createElement('div'); m.className = 'msg ' + who;
  const a = document.createElement('div'); a.className = 'ava' + (who==='me' ? ' me' : '');
  if(who==='me') a.textContent = '🧑'; else catFill(a);
  const b = document.createElement('div'); b.className = 'bub'; b.textContent = text;
  m.appendChild(a); m.appendChild(b); log().appendChild(m); scroll(); return b;
}
msg('bot', timeGreeting() + '，心瑞主人～ 我是你专属的代码助手卢娜，(=^･ω･^=)ﾉ 今天想让我帮你做点什么呢？');

const short = t => (t||'').split('::').pop();
function chip(label, val){ return "<span class='chip'>" + label + " <b>" + esc(val) + "</b></span>"; }
function chipC(label, val, cls){ return "<span class='chip" + (cls ? ' ' + cls : '') + "'>" + label + " <b>" + esc(val) + "</b></span>"; }
function leadText(d){        // 修完后卢娜说的第一句话（口吻润色，数字全来自真实结果）
  const nfix=(d.fixed||[]).length, nreg=(d.regressions||[]).length,
        nsf=(d.still_failing||[]).length, ntgt=(d.target||[]).length;
  if(d.solved) return "主人久等啦～ 那 " + nfix + " 个闹脾气的测试都被我一个个哄绿咯，原来好好的测试一个都没碰哦，可以放心用 (ฅ^•ﻌ•^ฅ)";
  if(nreg) return "呜…我修好了 " + nfix + " 个，可是手一抖把 " + nreg + " 个原本是绿的碰红了 (｡•́︿•̀｡) 主人先别急，这条分支我还没提交，随时能把我的改动还原回去。";
  if(nsf) return "唔…我尽力啦，修好了 " + nfix + "/" + ntgt + " 个，还有 " + nsf + " 个有点难缠，我一时没拿下…主人要不要再给我点提示，我重新试试？";
  return "唔…这次没能全部搞定呢，主人看看下面的细节好嘛？";
}
function renderDiff(diff){
  return diff.split('\n').map(function(l){
    let cls = '';
    if(l.indexOf('+++')===0 || l.indexOf('---')===0 || l.indexOf('diff ')===0 || l.indexOf('index ')===0) cls = 'dm';
    else if(l.charAt(0)==='+') cls = 'da';
    else if(l.charAt(0)==='-') cls = 'dd';
    else if(l.indexOf('@@')===0) cls = 'dh';
    return "<span class='" + cls + "'>" + esc(l) + "</span>";
  }).join('\n');
}
const PRE = ['not_git_repo','not_repo_root','dirty_tree','mid_operation','no_tests_collected','baseline_error','error'];
function renderResult(host, d){
  const S = d.baseline || {};
  if(PRE.indexOf(d.status) >= 0){
    host.innerHTML = "<span class='pill bad'>✗ 呜…没能开始</span><div class='branch'>" + esc(d.message||d.status) + "</div>"; scroll(); return;
  }
  const baseChips = chip('基线 passed', S.passed||0) + chip('failed', S.failed||0) + ((S.error||0) ? chip('error', S.error) : '');
  if(d.status === 'no_failing_tests'){
    host.innerHTML = "<span class='pill neutral'>✓ 全是绿灯呀</span><div class='chips'>" + baseChips + "</div>" +
      "<div class='branch'>这个仓库的测试全是绿的呢，没有红灯要修～ 我只擅长把红灯变绿灯哦 (=^･ω･^=)</div>"; scroll(); return;
  }
  let h = d.solved ? "<span class='pill ok'>✅ 修好啦～</span>" : "<span class='pill bad'>呜…没能全部修好 (｡•́︿•̀｡)</span>";
  h += "<div class='lead'>" + leadText(d) + "</div>";
  const nreg = (d.regressions||[]).length;
  const nfiles = d.diff ? (d.diff.match(/diff --git /g)||[]).length : 0;
  h += "<div class='chips'>"
    + chip('基线', (S.passed||0)+'✓ / '+(S.failed||0)+'✗'+((S.error||0)?' / '+S.error+'⚠':''))
    + chipC('修复', (d.fixed||[]).length+' / '+(d.target||[]).length, 'good')
    + chipC('回归', nreg, nreg?'bad':'') + "</div>";
  h += "<div class='chips sub'>" + chip('步数', d.steps) + chip('成本', '$'+d.cost) + chip('耗时', d.wall+'s') + "</div>";
  if(nreg) h += "<div class='warn'>被碰红的：" + d.regressions.map(short).map(esc).join('、') + "</div>";
  if((d.still_failing||[]).length) h += "<div class='warn'>还没搞定的：" + d.still_failing.map(short).map(esc).join('、') + "</div>";
  h += "<div class='branch'>🌿 " + esc(d.branch||'?') + " @ " + esc(d.base_sha||'') + "（还没提交哦）</div>";
  if(d.diff) h += "<details><summary>看看我改了哪里呀～" + (nfiles ? "（"+nfiles+" 个文件）" : "") + "</summary><pre class='diff'>" + renderDiff(d.diff) + "</pre></details>";
  h += "<div class='hint'>改动都放在这条小分支上、还没提交哦～ 想留下就切过去；不想要的话跟我说一声，或 <code>git checkout . &amp;&amp; git clean -fd</code> 让它们乖乖消失 🌸</div>";
  host.innerHTML = h; scroll();
}
document.getElementById('f').addEventListener('submit', async function(e){
  e.preventDefault();
  const msgEl = document.getElementById('msg');
  const text = msgEl.value.trim();
  if(!text) return;
  msg('me', text);
  msgEl.value = '';
  const btn = document.getElementById('send'); btn.disabled = true; msgEl.disabled = true;
  const t = document.createElement('div'); t.className = 'msg bot';
  const a = document.createElement('div'); a.className = 'ava'; catFill(a);
  const b = document.createElement('div'); b.className = 'bub typing'; b.innerHTML = "<span></span><span></span><span></span>";
  t.appendChild(a); t.appendChild(b); log().appendChild(t); scroll();
  try{
    const res = await fetch('/run', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({message:text})});
    const d = await res.json();
    if(d.status === 'chat'){ b.className = 'bub'; b.textContent = d.reply || '喵～'; scroll(); }
    else{ b.className = 'bub rc'; renderResult(b, d); }
  }catch(err){
    b.className = 'bub rc'; b.innerHTML = "<span class='pill bad'>✗ 请求失败</span><div class='branch'>" + esc(String(err)) + "</div>";
  }finally{ btn.disabled = false; msgEl.disabled = false; msgEl.focus(); }
});
