"""One self-contained local replay page, no server or third-party assets."""

import json
from pathlib import Path


def write_replay(path, *, trace, makespan, score, instance):
    data = json.dumps({'trace': trace, 'makespan': makespan, 'score': score,
                       'instance': instance}, ensure_ascii=False, allow_nan=False)
    # Data stays inert even if an instance name contains HTML/script markup.
    data = data.replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    html = '''<!doctype html><html lang="zh"><meta charset="utf-8">
<title>FJSP 实际排程回放</title><style>
body{font:15px system-ui;max-width:1050px;margin:24px auto;padding:12px;color:#183047}
table{border-collapse:collapse;width:100%;margin:12px 0}td,th{border-bottom:1px solid #ddd;padding:7px;text-align:left}
input{width:80%}pre{white-space:pre-wrap;background:#f2f5f8;padding:12px}svg{width:100%;height:220px}
</style><h1>FJSP 实际排程回放</h1><p id="summary"></p>
<p>演示 H 与手写 U 的真实运行记录。拖动查看每一步；不包含 LLM 或正式演化结果。</p>
<input id="slider" type="range" min="0" value="0"><span id="step"></span>
<h3>U 的七项状态输入</h3><pre id="state"></pre>
<h3>本步动作：同一个 h 评分</h3><p id="member"></p><table><thead><tr>
<th>工序（从 0 编号）</th><th>机器</th><th>开始—结束</th><th>分数</th><th>选择</th>
</tr></thead><tbody id="actions"></tbody></table><h3>已执行排程</h3><svg id="gantt" viewBox="0 0 1000 220"></svg>
<script id="data" type="application/json">DATA</script><script>
const d=JSON.parse(document.getElementById('data').textContent), by=id=>document.getElementById(id);
by('summary').textContent=`实例 ${d.instance} · makespan ${d.makespan} · 归一化分数 ${d.score}`;
by('slider').max=d.trace.length-1;
function svg(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text)e.textContent=text;return e;}
function render(){const i=+by('slider').value,t=d.trace[i];by('step').textContent=` ${i+1} / ${d.trace.length}`;
by('state').textContent=JSON.stringify(t.state,null,2);by('member').textContent=`U 本步调用一次，选择成员 ${t.member_id}（0=EFT，1=SPT）；合法动作 ${t.action_count} 个${t.actions_truncated?'，动作列表已截断':''}`;
by('actions').replaceChildren();for(const a of t.actions){const row=document.createElement('tr');const chosen=['job','operation','machine'].every(k=>a[k]===t.chosen[k]);for(const value of [`J${a.job} O${a.operation}`,`M${a.machine}`,`${a.start}—${a.end}`,a.score,chosen?'✓':'']){const cell=document.createElement('td');cell.textContent=value;row.append(cell);}by('actions').append(row);}
const g=by('gantt');g.replaceChildren();const n=1+Math.max(...d.trace.map(t=>t.chosen.machine)),h=180/n;
for(let m=0;m<n;m++)g.append(svg('text',{x:5,y:25+m*h},`M${m}`));
for(const t of d.trace.slice(0,i+1)){const a=t.chosen,x=70+880*a.start/d.makespan,w=880*(a.end-a.start)/d.makespan,y=5+a.machine*h;g.append(svg('rect',{x,y,width:w,height:h-8,fill:['#64b5c5','#e6b362','#a294df'][a.job%3]}));g.append(svg('text',{x:x+4,y:y+20},`J${a.job} O${a.operation}: ${a.start}—${a.end}`));}}
by('slider').addEventListener('input',render);render();</script></html>'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html.replace('>DATA<', '>' + data + '<'), encoding='utf-8')
