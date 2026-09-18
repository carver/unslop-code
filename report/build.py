import json, pathlib, collections, datetime
R = sorted(p.parent for p in pathlib.Path('outputs/dev6').glob('*/*/checkpoint_results.jsonl'))[-1]
rows = [json.loads(line) for line in (R/'checkpoint_results.jsonl').read_text().splitlines()]
diff = {line.split(',')[0]: line.split(',')[1] for line in pathlib.Path('problems.csv').read_text().splitlines()[1:]}
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

def run_stats(R):
    rows2=[json.loads(line) for line in (R/'checkpoint_results.jsonl').read_text().splitlines()]
    for r in rows2:
        scb=R/r['problem']/r['checkpoint']/'quality_analysis'/'scb_check.json'
        if scb.exists():
            d=json.loads(scb.read_text()); t=d.get('total_loc') or 0
            r['erosion']=d.get('erosion'); r['verbosity']=d.get('verbosity')
            r['ast']=(d.get('ast_grep_flagged_loc') or 0)/t if t else None
            r['cloned']=(d.get('clone_loc') or 0)/t if t else None
    n2=len(rows2)
    m=lambda k: sum(r[k] for r in rows2 if r.get(k) is not None)/max(1,sum(1 for r in rows2 if r.get(k) is not None))
    return rows2, dict(n=n2, strict=100*sum(r['strict_pass_rate']==1 for r in rows2)/n2,
        iso=100*sum(r['isolated_pass_rate']==1 for r in rows2)/n2,
        core=100*sum(r['core_pass_rate']==1 for r in rows2)/n2,
        cpc=sum(r['cost'] for r in rows2)/n2, erosion=m('erosion'), verbosity=m('verbosity'), ast=m('ast'), cloned=m('cloned'))

def latest(pattern):
    hits = sorted(q.parent for q in pathlib.Path('.').glob(pattern + '/*/*/checkpoint_results.jsonl'))
    return hits[-1] if hits else None

probe_runs = [('Opus 5', latest('outputs/dev6-opus5')), ('Fable 5', latest('outputs/dev6-fable5'))]
probe_runs = [(name, r) for name, r in probe_runs if r]
PROBE_HEAD = PROBE_PROB = PROBE_COLS = ''
if probe_runs:
    probe_stats = [('Sonnet 4.6', run_stats(R)[1])] + [(name, run_stats(r)[1]) for name, r in probe_runs]
    PROBE_COLS = ''.join(f"<th class=n>{name}</th>" for name, _ in probe_stats)
    def fmt_rows(picks):
        out = ''
        for label, key, f in picks:
            out += f"<tr><th scope=row>{label}</th>" + ''.join(f"<td class=n>{f(st[1][key])}</td>" for st in probe_stats) + "</tr>"
        return out
    PROBE_HEAD = fmt_rows([
        ('Strict solve', 'strict', lambda v: f"{v:.1f}%"), ('Isolated solve', 'iso', lambda v: f"{v:.1f}%"),
        ('Core solve', 'core', lambda v: f"{v:.1f}%"), ('$ / checkpoint', 'cpc', lambda v: f"${v:.2f}"),
        ('Erosion', 'erosion', lambda v: f"{v:.3f}"), ('Verbosity', 'verbosity', lambda v: f"{v:.3f}"),
        ('AST-grep flagged', 'ast', lambda v: f"{v:.3f}"), ('Cloned', 'cloned', lambda v: f"{v:.3f}")])
    def per_problem(rws):
        by = collections.defaultdict(list)
        for r in rws: by[r['problem']].append(r)
        return {p: (sum(r['strict_pass_rate']==1 for r in rs), sum(r['isolated_pass_rate']==1 for r in rs),
                    sum(r['core_pass_rate']==1 for r in rs), len(rs), sum(r['cost'] for r in rs)) for p, rs in by.items()}
    tables = [per_problem(rows)] + [per_problem(run_stats(r)[0]) for _, r in probe_runs]
    for p in sorted(tables[0]):
        PROBE_PROB += f"<tr><th scope=row>{p}</th><td>{diff[p]}</td>" + ''.join(
            f"<td class=n>{t[p][0]}/{t[p][1]}/{t[p][2]} of {t[p][3]}</td><td class=n>{t[p][4]:.2f}</td>" for t in tables) + "</tr>"

page = pathlib.Path('report/template.html').read_text()
for k, v in dict(PROB_TABLE=prob_table, CK_TABLE=ck_table, BARS=bars,
                 S_STRICT=f"{stats['strict']:.1f}", S_ISO=f"{stats['iso']:.1f}", S_CORE=f"{stats['core']:.1f}", S_CPC=f"{stats['cpc']:.2f}",
                 S_EROSION=f"{stats['erosion']:.3f}", S_VERB=f"{stats['verbosity']:.3f}", S_AST=f"{stats['ast']:.3f}", S_CLONED=f"{stats['cloned']:.3f}",
                 T_IN=f"{toks['input']:,}", T_OUT=f"{toks['output']:,}", T_CR=f"{toks['cache_read']:,}", T_CW=f"{toks['cache_write']:,}", T_ALL=f"{sum(toks.values())/1e6:.1f}M",
                 N_STRICT=str(tot['s']), N_ISO=str(tot['i']), N_CORE=str(tot['c']), COST=f"{tot['cost']:.2f}", WALL=f"{tot['el']/3600:.1f}", RUNDIR=str(R),
                 PROBE_HEAD=PROBE_HEAD, PROBE_PROB=PROBE_PROB, PROBE_COLS=PROBE_COLS).items():
    page = page.replace('{{'+k+'}}', v)
assert '{{' not in page, [line for line in page.splitlines() if '{{' in line][:3]
out = pathlib.Path('report/scbench-baseline.html')
out.write_text(page); print(out, len(page))
