const $ = (id) => document.getElementById(id);
const state = { categories: [], brands: [], polling: null, settings: null, platform: '1688' };

async function api(url, options={}) {
  const response = await fetch(url, {headers:{'Content-Type':'application/json'}, ...options});
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

const num = (value) => value == null ? '—' : Number(value).toLocaleString('zh-CN', {maximumFractionDigits:1});
const pct = (value) => value == null ? '—' : `${(value*100).toFixed(1)}%`;
const esc = (value='') => String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const fieldValue = (id, fallback) => $(id)?.value ?? fallback;
const fieldChecked = (id, fallback=false) => $(id)?.checked ?? fallback;
function imageFallback(img) {
  const placeholder = document.createElement('div');
  placeholder.className = 'image-placeholder';
  placeholder.textContent = '无图';
  img.replaceWith(placeholder);
}

function categoryCard(category={name:'', enabled:true, keywords:[]}) {
  const words = (category.keywords || []).map(k => typeof k === 'string' ? k : k.value);
  return `<article class="category-card">
    <div class="category-card-head">
      <input data-role="name" value="${esc(category.name)}" placeholder="例如：染发护理" aria-label="品类名称">
      <label class="category-enabled"><input data-role="enabled" type="checkbox" ${category.enabled !== false ? 'checked' : ''}> 启用采集</label>
      <button type="button" class="delete-category" aria-label="删除品类">删除</button>
    </div>
    <textarea data-role="keywords" rows="3" placeholder="每行一个搜索词">${esc(words.join('\n'))}</textarea>
  </article>`;
}

function renderCategoryEditor() {
  $('categoryRows').innerHTML = state.categories.map(categoryCard).join('');
}

async function loadCategories() {
  const selected = $('keywordFilter').value;
  state.categories = await api('/api/categories');
  $('keywordFilter').innerHTML = '<option value="">全部品类</option>' + state.categories.map(c => `<option value="${c.id}">${esc(c.name)}${c.enabled ? '' : '（已停用）'}</option>`).join('');
  if ([...$('keywordFilter').options].some(option => option.value === selected)) $('keywordFilter').value = selected;
  renderCategoryEditor();
}

async function loadSettings() {
  const settings = await api('/api/settings');
  state.settings = settings;
  $('autoEnabled').checked = settings.auto_enabled;
  $('dailyStartHour').value = settings.daily_start_hour;
  $('batchSize').value = settings.batch_size;
  $('pagesPerKeyword').value = settings.pages_per_keyword;
  $('minDelaySeconds').value = settings.min_delay_seconds;
}

async function loadBrands() {
  state.brands = await api('/api/brands');
  $('brandRules').value = state.brands.filter(item=>item.enabled).map(item=>[item.name, ...(item.aliases||[])].join(' | ')).join('\n');
}

async function loadOverview() {
  const douyin = state.platform === 'douyin';
  const hideBrands = fieldChecked('hideBrands', true);
  const data = await api(`${douyin ? '/api/douyin/overview' : '/api/overview'}?hide_brands=${hideBrands}`);
  $('productCount').textContent = num(douyin ? data.opportunity_count : data.product_count);
  $('growthReady').textContent = num(douyin ? data.growing_count : data.growth_ready);
  $('highRisk').textContent = num(douyin ? data.source_count : data.high_risk);
  $('brandFilteredCount').textContent = num(data.brand_blocked_count || 0);
  const run = data.latest_run;
  $('runStatus').textContent = !run ? '未运行' : ({running:'采集中',success:'成功',failed:'失败'}[run.status] || run.status);
  $('collectBtn').disabled = run?.status === 'running';
  $('douyinCollectBtn').disabled = douyin && run?.status === 'running';
  if (run?.status === 'running') startPolling(); else stopPolling();
}

async function loadDouyin() {
  const items = await api(`/api/douyin/opportunities?hide_brands=${fieldChecked('hideBrands', true)}`);
  $('douyinEmpty').style.display = items.length ? 'none' : 'block';
  $('douyinRows').innerHTML = items.map((item,i)=>{
    const benefits = item.benefits.length ? item.benefits.map(v=>`<span class="benefit">${esc(v)}</span>`).join('') : '—';
    const source = item.has_source ? `<button class="op-action source-action" data-id="${item.id}">官方货源</button>` : '<button class="op-action" disabled>暂无货源</button>';
    const brand = item.brand_status === 'blocked' ? `<span class="brand-blocked">${esc(item.brand_reason)}</span>` : item.brand_status === 'review' ? `<span class="brand-review">${esc(item.brand_reason)}</span>` : '';
    return `<tr><td>${i+1}</td><td class="title"><strong>${esc(item.title)}</strong>${brand}<small>已采集 ${num(item.snapshot_count)} 次 · 第 ${num(item.source_page)} 页</small></td><td>${esc(item.search_volume_text||'—')}</td><td class="${(item.growth_rate||0)>0?'positive':''}">${pct(item.growth_rate)}</td><td>${esc(item.recommendation||'—')}</td><td>${benefits}</td><td>${item.has_source?'<span class="source-yes">可找货源</span>':'<span class="muted">暂无</span>'}</td><td><span class="score">${num(item.score)}</span></td><td><div class="op-actions"><button class="op-action products-action" data-id="${item.id}">抖音爆品</button>${source}<a class="op-action alibaba-action" target="_blank" rel="noopener" href="${esc(item.alibaba_url)}">1688同款</a></div></td><td>${new Date(item.collected_at).toLocaleString('zh-CN')}</td></tr>`;
  }).join('');
}

function switchPlatform() {
  state.platform = $('platformFilter').value;
  const douyin = state.platform === 'douyin';
  document.querySelectorAll('.platform-1688').forEach(el=>el.classList.toggle('hidden',douyin));
  document.querySelectorAll('.platform-douyin').forEach(el=>el.classList.toggle('hidden',!douyin));
  $('productTableWrap').classList.toggle('hidden',douyin);
  $('douyinTableWrap').classList.toggle('hidden',!douyin);
  $('countLabel').textContent = douyin ? '抖音商机词' : '候选商品';
  $('growthLabel').textContent = douyin ? '成交增长中' : '已有增长数据';
  $('riskLabel').textContent = douyin ? '有代发货源' : '高风险宣称';
  $('noticeText').innerHTML = douyin ? '<strong>抖音商机数据来自官方商机中心。</strong> 默认隐藏品牌机会词；疑似品牌仍展示并标记，成交增速与1688销量分开排名。' : '<strong>增长榜按相邻两天同一时段计算。</strong> 默认隐藏明确品牌商品；疑似品牌仍展示并标记，只有约24小时且销量口径一致的快照才参与增长计算。';
  refresh();
}

async function loadProducts() {
  const qs = new URLSearchParams({min_sales:$('minSales').value||0, hide_brands:fieldChecked('hideBrands', true)});
  if ($('keywordFilter').value) qs.set('category_id', $('keywordFilter').value);
  const products = await api(`/api/products?${qs}`);
  $('emptyState').style.display = products.length ? 'none' : 'block';
  $('productRows').innerHTML = products.map((p,i) => {
    const cls = (p.sales_delta || 0) > 0 ? 'positive' : (p.sales_delta || 0) < 0 ? 'negative' : '';
    const riskItems = [...p.risk_flags];
    if (p.brand_status !== 'safe') riskItems.unshift(p.brand_reason);
    const risks = riskItems.length ? riskItems.map((r,index)=>`<span class="${index===0&&p.brand_status==='blocked'?'brand-blocked':index===0&&p.brand_status==='review'?'brand-review':'risk'}">${esc(r)}</span>`).join('') : '<span class="safe">未命中</span>';
    const image = p.image_url ? `<img src="${esc(p.image_url)}" referrerpolicy="no-referrer" loading="lazy" onerror="imageFallback(this)">` : '<div class="image-placeholder">无图</div>';
    const delta = p.data_quality_issue ? `<span class="risk" title="${esc(p.data_quality_issue)}">异常已排除</span>` : (p.sales_delta==null?'待次日':(p.sales_delta>0?'+':'')+num(p.sales_delta));
    const confidenceLabel = p.data_quality_issue ? '异常' : ({baseline:'待次日',medium:'有效',high:'高'}[p.confidence]);
    return `<tr><td>${i+1}</td><td class="title"><div class="product">${image}<div><a target="_blank" href="${esc(p.url)}">${esc(p.title)}</a><small>${esc(p.keyword)} · ${esc(p.shop_name||'供应商待识别')}</small></div></div></td><td>¥${num(p.price_min)}</td><td>${num(p.sales_count)}</td><td class="${cls}">${delta}</td><td class="${cls}">${p.daily_velocity==null?'—':(p.daily_velocity>0?'+':'')+num(p.daily_velocity)}</td><td class="${cls}">${pct(p.growth_rate)}</td><td><span class="score">${num(p.score)}</span></td><td>${risks}</td><td><span class="confidence ${p.confidence}" title="${esc(p.comparison_note)}">${confidenceLabel}</span></td></tr>`;
  }).join('');
}

async function refresh() { try { await Promise.all([loadOverview(), state.platform==='douyin'?loadDouyin():loadProducts()]); } catch(e) { message(e.message, true); } }
function message(text, error=false){ $('message').textContent=text; $('message').style.color=error?'#a83d2e':''; }
function startPolling(){ if(state.polling)return; state.polling=setInterval(refresh,3000); }
function stopPolling(){ if(state.polling){clearInterval(state.polling);state.polling=null;} }

async function collect(mode){
  try { if(mode==='live') $('collectBtn').disabled=true; const r=await api('/api/collect',{method:'POST',body:JSON.stringify({mode})}); message(`任务 #${r.run_id} 已启动，请等待完成`); startPolling(); await refresh(); }
  catch(e){$('collectBtn').disabled=false;message(e.message,true);}
}

async function collectDouyin(){
  try { $('douyinCollectBtn').disabled=true; const r=await api('/api/douyin/collect',{method:'POST',body:JSON.stringify({pages:Number(fieldValue('douyinPages',2)||2)})}); message(`抖音任务 #${r.run_id} 已启动，首次运行请在Chrome中登录`); startPolling(); await refresh(); }
  catch(e){$('douyinCollectBtn').disabled=false;message(e.message,true);}
}

async function openDouyin(itemId, action) {
  try {
    const label = action === 'source' ? '官方货源' : '抖音爆品';
    const result = await api(`/api/douyin/opportunities/${itemId}/open`, {method:'POST', body:JSON.stringify({action})});
    if (result.accepted) message(`${label}窗口正在打开；查看完成后请关闭该Chrome窗口`);
  } catch(e) { message(e.message, true); }
}

$('collectBtn').onclick=()=>collect('live');
$('demoBtn').onclick=()=>collect('demo');
$('douyinCollectBtn').onclick=collectDouyin;
$('douyinRows').onclick=(event)=>{
  const button = event.target.closest('button[data-id]');
  if (!button) return;
  openDouyin(Number(button.dataset.id), button.classList.contains('source-action') ? 'source' : 'products');
};
$('refreshBtn').onclick=refresh;
$('hideBrands').onchange=refresh;
$('platformFilter').onchange=switchPlatform;
$('keywordFilter').onchange=loadProducts;
$('keywordBtn').onclick=()=>{renderCategoryEditor();$('keywordDialog').showModal();};
$('brandBtn').onclick=()=>{$('brandDialog').showModal();};
$('addCategory').onclick=()=>{$('categoryRows').insertAdjacentHTML('beforeend',categoryCard());};
$('categoryRows').onclick=(event)=>{if(event.target.classList.contains('delete-category')&&confirm('确定删除这个品类吗？保存后才会生效。'))event.target.closest('.category-card').remove();};
$('saveSettings').onclick=async()=>{try{await api('/api/settings',{method:'PUT',body:JSON.stringify({auto_enabled:fieldChecked('autoEnabled'),interval_hours:state.settings?.interval_hours||12,daily_start_hour:Number(fieldValue('dailyStartHour',13)||13),batch_size:Number(fieldValue('batchSize',2)||2),pages_per_keyword:Number(fieldValue('pagesPerKeyword',2)||2),min_delay_seconds:Number(fieldValue('minDelaySeconds',20)||20)})});await loadSettings();message('每日采集设置已保存');}catch(e){message(e.message,true)}};
$('saveKeywords').onclick=async()=>{try{const categories=[...$('categoryRows').querySelectorAll('.category-card')].map(card=>({name:card.querySelector('[data-role="name"]').value.trim(),enabled:card.querySelector('[data-role="enabled"]').checked,keywords:card.querySelector('[data-role="keywords"]').value.split('\n').map(v=>v.trim()).filter(Boolean)}));await api('/api/categories',{method:'PUT',body:JSON.stringify({categories})});await loadCategories();$('keywordDialog').close();await loadProducts();message('品类和采集关键词已保存');}catch(e){message(e.message,true)}};
$('saveBrands').onclick=async()=>{try{const brands=$('brandRules').value.split('\n').map(line=>line.split(/[|｜]/).map(v=>v.trim()).filter(Boolean)).filter(parts=>parts.length).map(parts=>({name:parts[0],aliases:parts.slice(1),enabled:true}));await api('/api/brands',{method:'PUT',body:JSON.stringify({brands})});await loadBrands();$('brandDialog').close();await refresh();message(`品牌词库已保存，共 ${brands.length} 个品牌`);}catch(e){message(e.message,true)}};

(async()=>{try{await Promise.all([loadCategories(),loadSettings(),loadBrands()]);await refresh();}catch(e){message(`页面初始化失败：${e.message}`,true);}})();
