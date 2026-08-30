import json, pathlib, collections, datetime, html
R = sorted(p.parent for p in pathlib.Path('outputs/dev6').glob('*/*/checkpoint_results.jsonl'))[-1]
rows = [json.loads(l) for l in open(R/'checkpoint_results.jsonl')]
diff = {l.split(',')[0]: l.split(',')[1] for l in open('problems.csv').read().splitlines()[1:]}
for r in rows:
    scb = R/r['problem']/r['checkpoint']/'quality_analysis'/'scb_check.json'
    d = json.loads(scb.read_text()); t = d.get('total_loc') or 0
    r['erosion'] = d.get('erosion'); r['verbosity'] = d.get('verbosity')
    r['ast'] = (d.get('ast_grep_flagged_loc') or 0)/t if t else None
    r['cloned'] = (d.get('clone_loc') or 0)/t if t else None
    r['capped'] = 'error_max_turns' in (R/r['problem']/r['checkpoint']/'agent'/'stdout.jsonl').read_text()[-3000:]
    r['elapsed'] = (datetime.datetime.fromisoformat(r['ended'])-datetime.datetime.fromisoformat(r['started'])).total_seconds()
rows.sort(key=lambda r: (r['problem'], r['idx']))
def chip(ok, extra=''):
    return f'<span class="chip {"ok" if ok else "miss"}{extra}">{"solved" if ok else "missed"}</span>'
def num(v, f='{:.3f}'):
    return '&ndash;' if v is None else f.format(v)
# per-problem
by = collections.defaultdict(list)
for r in rows: by[r['problem']].append(r)
prob_rows = []; tot = collections.Counter()
for p, rs in sorted(by.items()):
    n=len(rs); s=sum(r['strict_pass_rate']==1 for r in rs); i=sum(r['isolated_pass_rate']==1 for r in rs); c=sum(r['core_pass_rate']==1 for r in rs)
    cost=sum(r['cost'] for r in rs); el=sum(r['elapsed'] for r in rs); st=sum(r['steps'] for r in rs); cap=sum(r['capped'] for r in rs)
    prob_rows.append(dict(p=p,d=diff[p],n=n,s=s,i=i,c=c,cost=cost,cpc=cost/n,mpc=el/60/n,spc=st/n,cap=cap))
    tot.update(dict(n=n,s=s,i=i,c=c,cost=cost,el=el,st=st,cap=cap))
maxcpc = max(x['cpc'] for x in prob_rows)
prob_table = ''.join(f"<tr><th scope=row>{x['p']}</th><td>{x['d']}</td><td class=n>{x['n']}</td><td class=n>{x['s']}</td><td class=n>{x['i']}</td><td class=n>{x['c']}</td><td class=n>{x['cost']:.2f}</td><td class=n>{x['cpc']:.2f}</td><td class=n>{x['mpc']:.1f}</td><td class=n>{x['spc']:.0f}</td><td class=n>{x['cap'] or ''}</td></tr>" for x in prob_rows)
n=tot['n']
prob_table += f"<tr class=total><th scope=row>all six</th><td>2E / 2M / 2H</td><td class=n>{n}</td><td class=n>{tot['s']}</td><td class=n>{tot['i']}</td><td class=n>{tot['c']}</td><td class=n>{tot['cost']:.2f}</td><td class=n>{tot['cost']/n:.2f}</td><td class=n>{tot['el']/60/n:.1f}</td><td class=n>{tot['st']/n:.0f}</td><td class=n>{tot['cap']}</td></tr>"
bars = ''.join(f'<li><span class=lbl>{x["p"]} <em>{x["d"]}</em></span><span class=track><span class=bar style="width:{100*x["cpc"]/maxcpc:.1f}%" tabindex=0 title="{x["p"]}: ${x["cpc"]:.2f} per checkpoint over {x["n"]} checkpoints"></span></span><span class=val>${x["cpc"]:.2f}</span></li>' for x in sorted(prob_rows, key=lambda x:-x['cpc']))
ck_table = ''.join(
  f"<tr><th scope=row>{r['problem']} <span class=idx>{r['idx']}</span></th><td>{chip(r['strict_pass_rate']==1)}</td><td>{chip(r['isolated_pass_rate']==1)}</td><td>{chip(r['core_pass_rate']==1)}</td>"
  f"<td class=n>{r['core_pass_rate']:.2f}</td><td class=n>{r['steps']}{' <span class=cap title=\"ended by --max-turns 100\">cap</span>' if r['capped'] else ''}</td><td class=n>{r['output']:,}</td><td class=n>{r['cache_read']/1e6:.2f}M</td><td class=n>{r['cache_write']/1e3:.0f}k</td>"
  f"<td class=n>{r['cost']:.2f}</td><td class=n>{r['elapsed']/60:.1f}</td><td class=n>{num(r['erosion'])}</td><td class=n>{num(r['verbosity'])}</td><td class=n>{num(r['ast'])}</td><td class=n>{num(r['cloned'])}</td></tr>" for r in rows)
toks = {k: sum(r[k] for r in rows) for k in ('input','output','cache_read','cache_write')}
mean = lambda k: sum(r[k] for r in rows if r[k] is not None)/sum(1 for r in rows if r[k] is not None)
stats = dict(strict=100*tot['s']/n, iso=100*tot['i']/n, core=100*tot['c']/n, cpc=tot['cost']/n, erosion=mean('erosion'), verbosity=mean('verbosity'), ast=mean('ast'), cloned=mean('cloned'))

page = open('report/template.html').read()
for k, v in dict(PROB_TABLE=prob_table, CK_TABLE=ck_table, BARS=bars,
                 S_STRICT=f"{stats['strict']:.1f}", S_ISO=f"{stats['iso']:.1f}", S_CORE=f"{stats['core']:.1f}", S_CPC=f"{stats['cpc']:.2f}",
                 S_EROSION=f"{stats['erosion']:.3f}", S_VERB=f"{stats['verbosity']:.3f}", S_AST=f"{stats['ast']:.3f}", S_CLONED=f"{stats['cloned']:.3f}",
                 T_IN=f"{toks['input']:,}", T_OUT=f"{toks['output']:,}", T_CR=f"{toks['cache_read']:,}", T_CW=f"{toks['cache_write']:,}", T_ALL=f"{sum(toks.values())/1e6:.1f}M",
                 N_STRICT=str(tot['s']), N_ISO=str(tot['i']), N_CORE=str(tot['c']), COST=f"{tot['cost']:.2f}", WALL=f"{tot['el']/3600:.1f}", RUNDIR=str(R)).items():
    page = page.replace('{{'+k+'}}', v)
assert '{{' not in page, [l for l in page.splitlines() if '{{' in l][:3]
out = pathlib.Path('report/scbench-baseline.html')
out.write_text(page); print(out, len(page))
