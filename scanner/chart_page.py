"""K 线图页（chart.html）的 HTML/JS。数据来自 site/chart/<SYM>.json（由 chart.py 生成），图表库为本地 assets/echarts.min.js。"""
import json

SECTOR_ORDER = ["农产品", "能化", "黑色", "有色", "贵金属", "股指", "新能源"]

CSS = """
.ck{display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;font-size:13px;color:var(--muted);margin:10px 0 6px}
.ck label{display:flex;align-items:center;gap:5px;cursor:pointer;user-select:none}.ck input{accent-color:var(--cyan)}
.ck select{font:inherit;font-size:13px;color:var(--ink);background:var(--panel2);border:1px solid var(--line2);border-radius:4px;padding:4px 8px}
.ck .sw{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:2px;vertical-align:-1px}
#chart{width:100%;height:760px}
@media (max-width:720px){#chart{height:620px}}
.legend-marks{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px 18px;font-size:12.5px;color:var(--muted);margin-top:8px}
.legend-marks b{color:var(--ink);font-weight:600}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-family:var(--mono);border:1px solid var(--line2)}
.chip.bull{color:var(--up);border-color:var(--up);background:var(--up-dim)}.chip.bear{color:var(--down);border-color:var(--down);background:var(--down-dim)}.chip.flat{color:var(--amber);border-color:var(--amber);background:var(--amber-dim)}
.hint{font-size:12px;color:var(--dim);margin-top:6px}
"""


def body(avail: list[dict], sector: dict) -> str:
    groups = {}
    for a in avail:
        groups.setdefault(sector.get(a["symbol"], "其他"), []).append(a)
    opts = ""
    for sec in SECTOR_ORDER + [s for s in groups if s not in SECTOR_ORDER]:
        if sec not in groups:
            continue
        opts += f"<optgroup label='{sec}'>" + "".join(
            f"<option value='{a['symbol']}'{' selected' if a['symbol'] == 'P0' else ''}>{a['name']} {a['symbol']}</option>" for a in groups[sec]) + "</optgroup>"
    return f"""<style>{CSS}</style>
<div class="hd"><h1>K 线形态图 <span id="ttl" class="sub"></span></h1>
<div class="sub">按《王刚期货交易体系手册（第二版）》规则逐根自动标注：蜡烛形态 · 包线 · 量仓价 · 趋势状态 · 摆动高低点</div></div>
<div class="card">
<div class="ck">
 <select id="sym">{opts}</select>
 <span id="meta" class="sub"></span>
 <label><input type="checkbox" id="ck_candle" checked><span class="sw" style="background:var(--up)"></span>蜡烛形态</label>
 <label><input type="checkbox" id="ck_bao" checked><span class="sw" style="background:var(--cyan)"></span>包线（2包/3包）</label>
 <label><input type="checkbox" id="ck_voloi" checked><span class="sw" style="background:var(--amber)"></span>量仓信号</label>
 <label><input type="checkbox" id="ck_regime" checked>趋势状态</label>
 <label><input type="checkbox" id="ck_swing">摆动高低点</label>
 <label><input type="checkbox" id="ck_ma60" checked>MA60</label>
</div>
<div id="chart"></div>
<div class="hint">鼠标悬停看当日明细；拖动底部滑块或滚轮缩放。标注只是规则命中，不是买卖建议；规则出处见每条标注的提示与 <a href="method.html">方法说明</a>。</div>
</div>
<div class="card"><h3>标注含义（手册出处）</h3>
<div class="legend-marks">
<div><b>吞没 / 穿头破脚</b>：后一根实体包住前一根实体、阴阳相反（4.4 太上皇）</div>
<div><b>乌云 / 刺透</b>：高开收在前阳实体中点下 / 低开收在前阴实体中点上</div>
<div><b>锤子 / 上吊</b>：长下影小实体，跌后为锤子、涨后为上吊</div>
<div><b>射星 / 倒锤</b>：长上影小实体，涨后为射星、跌后为倒锤</div>
<div><b>十字</b>：实体不足振幅 8%，仅在有趋势时标</div>
<div><b>红三兵 / 三黑鸦</b>：连续三根实体阳线抬高 / 阴线压低</div>
<div><b>2包 / 3包</b>：第 N+1 根高低包住前 N 根，不看阴阳（5.9）；三包是调整结束信号之一（4.5）</div>
<div><b>高富帅 / 白富美</b>：增仓·放量·上涨 / 下跌（2.3）；带 ★ 为量仓双 20%</div>
<div><b>增仓/减仓 20%</b>：一两天内增减仓 20% 会有大行情；高位减仓 20% 到顶、底部减仓 20% 到底（2.3）</div>
<div><b>趋势多头 / 空头 / 震荡观望</b>：MA5&gt;MA20&gt;MA60、收盘在 MA20 上、DIF&gt;DEA 为多头（反之空头），连续 3 日才切换（4.1、4.5）</div>
<div><b>H / L</b>：左右各 5 根内的最高 / 最低点，供数浪与三步判断顶底参考（4.3）</div>
<div><b>MACD</b>：参数 8、21、6（5.2 一堵）；<b>RSI</b> 14，80 以上 / 20 以下为过滤区（1.2）</div>
</div></div>
<script src="assets/echarts.min.js"></script>
<script>
(function(){{
var css=getComputedStyle(document.documentElement);
function v(n){{return css.getPropertyValue(n).trim();}}
var C={{up:v('--up'),down:v('--down'),cyan:v('--cyan'),amber:v('--amber'),ink:v('--ink'),muted:v('--muted'),dim:v('--dim'),line:v('--line'),panel:v('--panel')}};
var MA={{ma5:'#e0a100',ma10:'#3f8ff5',ma20:'#b85cff',ma60:'#8d6a3a'}};
var chart=echarts.init(document.getElementById('chart'),null,{{renderer:'canvas'}});
var D=null, sym=document.getElementById('sym');
var ck=function(id){{return document.getElementById(id).checked;}};
function load(s){{
  fetch('chart/'+s+'.json').then(function(r){{return r.json();}}).then(function(d){{D=d;render();}});
}}
function fmt(x){{return x==null?'-':(Math.abs(x)>=10000?x.toLocaleString('en-US'):(+x).toFixed(Math.abs(x)<10?2:1));}}
function render(){{
  if(!D)return;
  var n=D.dates.length, last=n-1;
  document.getElementById('ttl').textContent=D.name+' '+D.symbol+'（'+D.exchange+' 主力连续）';
  var rg=D.regime[last]; var cls=rg==='趋势多头'?'bull':rg==='趋势空头'?'bear':'flat';
  document.getElementById('meta').innerHTML=D.dates[0]+' ~ '+D.dates[last]+' · '+n+' 根 · 最新 '+fmt(D.ohlc[last][1])+' · <span class="chip '+cls+'">'+rg+'</span>';
  var byDay={{}}; D.marks.forEach(function(m){{(byDay[m.i]=byDay[m.i]||[]).push(m);}});
  // 标注散点：bear 在最高价上方，bull 在最低价下方；同日多个标注竖向错开
  var pts=[], off={{}};
  var rngPx=function(i){{var o=D.ohlc[i];return o[3]-o[2];}};
  var span=(function(){{var hs=D.ohlc.map(function(o){{return o[3];}}),ls=D.ohlc.map(function(o){{return o[2];}});return Math.max.apply(null,hs)-Math.min.apply(null,ls);}})();
  var step=span*0.018;
  D.marks.forEach(function(m){{
    var show=(m.k==='candle'&&ck('ck_candle'))||(m.k==='bao'&&ck('ck_bao'))||(m.k==='voloi'&&ck('ck_voloi'))||(m.k==='regime'&&ck('ck_regime'));
    if(!show)return;
    if(m.k==='voloi'&&m.s!=='oi')return; // 高富帅/白富美画在量柱区
    var o=D.ohlc[m.i]; var above=(m.s==='bear')||(m.k==='regime'&&m.s!=='bull')||(m.k==='voloi');
    var key=m.i+(above?'a':'b'); off[key]=(off[key]||0)+1;
    var y=above?o[3]+step*off[key]:o[2]-step*off[key];
    var col=m.k==='regime'?(m.s==='bull'?C.up:m.s==='bear'?C.down:C.amber):m.k==='bao'?C.cyan:m.k==='voloi'?C.amber:(m.s==='bull'?C.up:C.down);
    var txt=m.k==='regime'?'【'+m.t+'】':(m.k==='candle'?'★':'')+m.t;
    pts.push({{value:[m.i,y],name:txt,m:m,itemStyle:{{color:col}},label:{{color:col,fontWeight:m.k==='regime'?700:500,position:above?'top':'bottom'}}}});
  }});
  var sw=[]; if(ck('ck_swing')) D.swings.forEach(function(p){{var o=D.ohlc[p[0]];sw.push({{value:[p[0],p[1]==='H'?o[3]+step*1.2:o[2]-step*1.2],name:p[1],itemStyle:{{color:C.muted}},label:{{color:C.muted,fontSize:10,position:p[1]==='H'?'top':'bottom'}}}});}});
  var volC=D.vol.map(function(x,i){{var o=D.ohlc[i];return {{value:x,itemStyle:{{color:o[1]>=o[0]?C.up:C.down,opacity:.75}}}};}});
  var volMarks=[]; D.marks.forEach(function(m){{if(m.k==='voloi'&&m.s!=='oi'&&ck('ck_voloi'))volMarks.push({{value:[m.i,D.vol[m.i]],name:m.t,m:m,itemStyle:{{color:m.s==='bull'?C.up:C.down}},label:{{color:m.s==='bull'?C.up:C.down}}}});}});
  var macdC=D.macd.map(function(x){{return {{value:x,itemStyle:{{color:x>=0?C.up:C.down}}}};}});
  var start=Math.max(0,100-Math.round(160/n*100));
  var grids=[{{left:56,right:64,top:36,height:'50%'}},{{left:56,right:64,top:'59%',height:'10%'}},{{left:56,right:64,top:'72%',height:'11%'}},{{left:56,right:64,top:'86%',height:'9%'}}];
  var xa=function(i){{return {{type:'category',gridIndex:i,data:D.dates,boundaryGap:true,axisLine:{{lineStyle:{{color:C.line}}}},axisTick:{{show:false}},axisLabel:{{show:i===3,color:C.muted,fontSize:11}},splitLine:{{show:false}},min:'dataMin',max:'dataMax',axisPointer:{{label:{{show:i===3}}}}}};}};
  var ya=function(i,name){{return {{gridIndex:i,scale:true,position:'right',name:name,nameTextStyle:{{color:C.dim,fontSize:10,align:'right'}},nameGap:4,axisLine:{{show:false}},axisTick:{{show:false}},axisLabel:{{color:C.muted,fontSize:11,formatter:function(v){{return i===1||i===3?(v>=1e6?(v/1e6).toFixed(1)+'M':v>=1e3?(v/1e3).toFixed(0)+'k':v):v;}}}},splitLine:{{lineStyle:{{color:C.line,opacity:.6}}}},splitNumber:i===0?6:3}};}};
  var opt={{
    animation:false,backgroundColor:'transparent',
    textStyle:{{fontFamily:v('--sans')}},
    legend:{{top:6,left:56,textStyle:{{color:C.muted,fontSize:11}},itemWidth:14,itemHeight:2,data:['MA5','MA10','MA20','MA60']}},
    axisPointer:{{link:[{{xAxisIndex:'all'}}],lineStyle:{{color:C.muted,opacity:.6}},label:{{backgroundColor:C.muted}}}},
    tooltip:{{trigger:'axis',backgroundColor:C.panel,borderColor:C.line,textStyle:{{color:C.ink,fontSize:12}},confine:true,
      formatter:function(ps){{var i=ps[0].dataIndex;var o=D.ohlc[i];var chg=i>0?(o[1]-D.ohlc[i-1][1])/D.ohlc[i-1][1]*100:0;
        var h='<b>'+D.dates[i]+'</b> <span style="color:'+(chg>=0?C.up:C.down)+'">'+(chg>=0?'+':'')+chg.toFixed(2)+'%</span><br>';
        h+='开 '+fmt(o[0])+' 高 '+fmt(o[3])+' 低 '+fmt(o[2])+' 收 '+fmt(o[1])+'<br>';
        h+='MA5 '+fmt(D.ma5[i])+' · MA20 '+fmt(D.ma20[i])+' · MA60 '+fmt(D.ma60[i])+'<br>';
        h+='量 '+D.vol[i].toLocaleString('en-US')+' · 仓 '+D.oi[i].toLocaleString('en-US')+(i>0&&D.oi[i-1]?' ('+((D.oi[i]-D.oi[i-1])/D.oi[i-1]*100).toFixed(1)+'%)':'')+'<br>';
        h+='DIF '+fmt(D.dif[i])+' DEA '+fmt(D.dea[i])+' MACD '+fmt(D.macd[i])+' · RSI '+fmt(D.rsi[i])+' · '+(D.regime[i]||'-');
        (byDay[i]||[]).forEach(function(m){{h+='<br><span style="color:'+(m.s==='bull'?C.up:m.s==='bear'?C.down:C.amber)+'">● '+m.t+'</span> <span style="color:'+C.muted+'">'+m.d+'</span>';}});
        return h;}}}},
    grid:grids,
    xAxis:[xa(0),xa(1),xa(2),xa(3)],
    yAxis:[ya(0,''),ya(1,'成交量'),ya(2,'MACD 8/21/6'),ya(3,'持仓量')],
    dataZoom:[{{type:'inside',xAxisIndex:[0,1,2,3],start:start,end:100,minValueSpan:30}},{{type:'slider',xAxisIndex:[0,1,2,3],bottom:0,height:16,start:start,end:100,borderColor:C.line,fillerColor:'rgba(76,201,240,.15)',handleStyle:{{color:C.cyan}},textStyle:{{color:C.muted,fontSize:10}},dataBackground:{{lineStyle:{{color:C.dim}},areaStyle:{{color:C.line}}}}}}],
    series:[
      {{type:'candlestick',name:'日K',data:D.ohlc,itemStyle:{{color:C.up,color0:C.down,borderColor:C.up,borderColor0:C.down}},barMaxWidth:12}},
      {{type:'line',name:'MA5',data:D.ma5,showSymbol:false,lineStyle:{{width:1,color:MA.ma5}},itemStyle:{{color:MA.ma5}}}},
      {{type:'line',name:'MA10',data:D.ma10,showSymbol:false,lineStyle:{{width:1,color:MA.ma10}},itemStyle:{{color:MA.ma10}}}},
      {{type:'line',name:'MA20',data:D.ma20,showSymbol:false,lineStyle:{{width:1.2,color:MA.ma20}},itemStyle:{{color:MA.ma20}}}},
      {{type:'line',name:'MA60',data:ck('ck_ma60')?D.ma60:[],showSymbol:false,lineStyle:{{width:1.5,color:MA.ma60}},itemStyle:{{color:MA.ma60}}}},
      {{type:'scatter',name:'标注',data:pts,symbolSize:4,z:5,label:{{show:true,position:'top',fontSize:11,formatter:function(p){{return p.name;}}}},labelLayout:{{hideOverlap:true}},tooltip:{{show:false}}}},
      {{type:'scatter',name:'摆动',data:sw,symbolSize:4,z:4,label:{{show:true,position:'top',fontSize:10,formatter:function(p){{return p.name;}}}},tooltip:{{show:false}}}},
      {{type:'bar',name:'成交量',xAxisIndex:1,yAxisIndex:1,data:volC,barMaxWidth:12}},
      {{type:'scatter',name:'量仓',xAxisIndex:1,yAxisIndex:1,data:volMarks,symbolSize:5,z:5,label:{{show:true,position:'top',fontSize:10,formatter:function(p){{return p.name;}}}},labelLayout:{{hideOverlap:true}},tooltip:{{show:false}}}},
      {{type:'bar',name:'MACD',xAxisIndex:2,yAxisIndex:2,data:macdC,barMaxWidth:8}},
      {{type:'line',name:'DIF',xAxisIndex:2,yAxisIndex:2,data:D.dif,showSymbol:false,lineStyle:{{width:1,color:C.amber}}}},
      {{type:'line',name:'DEA',xAxisIndex:2,yAxisIndex:2,data:D.dea,showSymbol:false,lineStyle:{{width:1,color:MA.ma10}}}},
      {{type:'line',name:'持仓量',xAxisIndex:3,yAxisIndex:3,data:D.oi,showSymbol:false,lineStyle:{{width:1.3,color:MA.ma20}},areaStyle:{{color:MA.ma20,opacity:.08}}}}
    ]
  }};
  chart.setOption(opt,true);
}}
sym.addEventListener('change',function(){{load(sym.value);}});
['ck_candle','ck_bao','ck_voloi','ck_regime','ck_swing','ck_ma60'].forEach(function(id){{document.getElementById(id).addEventListener('change',render);}});
window.addEventListener('resize',function(){{chart.resize();}});
document.getElementById('themeBtn').addEventListener('click',function(){{setTimeout(function(){{css=getComputedStyle(document.documentElement);C={{up:v('--up'),down:v('--down'),cyan:v('--cyan'),amber:v('--amber'),ink:v('--ink'),muted:v('--muted'),dim:v('--dim'),line:v('--line'),panel:v('--panel')}};render();}},30);}});
var q=new URLSearchParams(location.search).get('s'); if(q){{sym.value=q;}}
load(sym.value);
}})();
</script>"""
