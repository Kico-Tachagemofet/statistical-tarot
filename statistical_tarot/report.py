"""An offline, dependency-free report for five-pile tarot observations.

Only display fields are rendered. Source paths, raw records, private prose,
and any other metadata in an input statistics document never enter the page.
"""
from __future__ import annotations

import html
import math
import os
from datetime import datetime
from pathlib import Path


_ELEMENTS = {"Fire": "火", "Water": "水", "Air": "风", "Earth": "土",
             "fire": "火", "water": "水", "air": "风", "earth": "土"}
_PILE_STYLE = {"fire": "fire", "water": "water", "air": "air", "earth": "earth", "major": "major"}
_CLASSES = {"minor_pip": "数字牌", "court": "宫廷牌", "major_arcana": "大阿卡那"}


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _num(value: object, fallback: float = 0.0) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
        return result if math.isfinite(result) else fallback
    except (ValueError, TypeError, OverflowError):
        return fallback


def _fmt(value: object, digits: int = 1) -> str:
    number = _num(value)
    if number == int(number):
        return f"{int(number):,}"
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def _signed(value: object, digits: int = 1) -> str:
    number = _num(value)
    if abs(number) < 0.5 * 10 ** -digits:
        return "0"
    return ("+" if number > 0 else "−") + _fmt(abs(number), digits)


def _p(value: object) -> str:
    """Never turn a positive tail probability into a displayed zero."""
    if value is None:
        return "未提供"
    number = _num(value, -1)
    if number < 0 or number > 1:
        return "未提供"
    if number == 0:
        return "低于计算精度"
    if number < 0.001:
        base, exponent = f"{number:.3e}".split("e")
        return f"{base.rstrip('0').rstrip('.')}e{int(exponent):+d}".replace("-", "−")
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _band(z: float) -> tuple[str, str]:
    if abs(z) >= 2:
        return "extreme", "极端候选"
    if abs(z) >= 1:
        return "ordinary", "普通偏离"
    return "near", "接近基线"


def _element(row: dict, highlight: dict, pile: dict) -> tuple[str, str]:
    """Read explicit tags only; do not infer a planetary major's element."""
    for item in (row, highlight):
        tag = item.get("element_tag")
        if isinstance(tag, dict) and tag.get("element"):
            value = str(tag["element"])
            return _ELEMENTS.get(value, value), str(tag.get("source") or "数据中的元素标注")
        if isinstance(tag, str) and tag:
            return _ELEMENTS.get(tag, tag), "数据中的元素标注"
    for item in (row, highlight):
        bt = item.get("book_t") if isinstance(item.get("book_t"), dict) else {}
        compound = item.get("element_compound") or bt.get("element_compound")
        if compound and isinstance(compound, str):
            pieces = compound.split(" of ")
            label = " · ".join(_ELEMENTS.get(piece, piece) for piece in pieces)
            return label, "Book T 复合元素：" + compound
        value = item.get("element") or bt.get("element")
        if isinstance(value, str) and value:
            return _ELEMENTS.get(value, value), "数据中的元素标注"
    if pile.get("key") != "major" and pile.get("element"):
        value = str(pile["element"])
        return _ELEMENTS.get(value, value), "花色元素（本堆归属）"
    return "未指定", "输入数据未提供元素标注；保留在大阿卡那堆"


def _stamp(value: object) -> str:
    if not value:
        return "离线报告"
    try:
        dt = datetime.fromisoformat(str(value))
        zone = dt.strftime("%z")
        zone = (" UTC" + zone[:3] + ":" + zone[3:]) if zone else ""
        return dt.strftime("%Y.%m.%d · %H:%M") + zone
    except (TypeError, ValueError):
        return "离线报告"


def _nice_max(number: float) -> float:
    if number <= 0:
        return 1
    step = 5 if number < 60 else 10 ** max(1, math.floor(math.log10(number)) - 1)
    return math.ceil(number * 1.08 / step) * step


def render_report(stats: dict) -> str:
    """Return a standalone Chinese HTML report without drawing any randomness."""
    piles = [p for p in stats.get("piles", []) if isinstance(p, dict)]
    protocol = stats.get("protocol") if isinstance(stats.get("protocol"), dict) else {}
    receipt = stats.get("receipt") if isinstance(stats.get("receipt"), dict) else {}
    n = int(_num(protocol.get("draws", receipt.get("draws", sum(_num(p.get("count")) for p in piles)))))
    total_cards = sum(len(p.get("cards", [])) for p in piles)
    question = _esc(stats.get("question") or "统计塔罗抽取报告")
    synthetic_badge = '<span class="synthetic-tag">合成示例 · SYNTHETIC</span>' if protocol.get("synthetic") is True else ''
    pile_scale = _nice_max(max((_num(p.get("count")) for p in piles), default=1))
    pile_scale = max(pile_scale, max((_num(p.get("expected")) for p in piles), default=1))
    all_cards: list[dict] = []
    for pi, pile in enumerate(piles):
        highlights = {h.get("card_id"): h for h in pile.get("highlights", []) if isinstance(h, dict)}
        for row in pile.get("cards", []):
            if not isinstance(row, dict):
                continue
            count = _num(row.get("count"))
            expected = _num(row.get("expected", pile.get("card_expected")))
            z = _num(row.get("z"))
            elem, source = _element(row, highlights.get(row.get("card_id"), {}), pile)
            band_key, band_label = _band(z)
            all_cards.append({"index": len(all_cards), "pile_index": pi, "pile": pile, "row": row,
                              "count": count, "expected": expected, "delta": count - expected,
                              "z": z, "element": elem, "element_source": source,
                              "band_key": band_key, "band_label": band_label})
    card_scale = _nice_max(max((max(c["count"], c["expected"]) for c in all_cards), default=1))
    near_count = sum(c["band_key"] == "near" for c in all_cards)
    extreme_count = sum(c["band_key"] == "extreme" for c in all_cards)
    ordinary_count = len(all_cards) - near_count - extreme_count
    pile_baselines = sorted({_num(p.get("expected")) for p in piles})
    baseline_copy = (f"每堆预期 {_fmt(pile_baselines[0])} 次" if len(pile_baselines) == 1
                     else "竖线标出各堆预期次数")
    parts = [f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="referrer" content="no-referrer">
<title>{question} · Statistical Tarot</title><style>{_CSS}</style></head><body>
<a class="skip-link" href="#explorer">跳到卡牌浏览</a>
<div class="page-shell"><header class="site-header"><a class="brand" href="#top" aria-label="Statistical Tarot，回到页首"><span class="brand-symbol" aria-hidden="true">✳</span><span>Statistical <em>Tarot</em></span></a><span class="offline"><i aria-hidden="true"></i>离线数据报告</span></header>
<main id="top"><section class="hero" aria-labelledby="report-title"><div class="hero-copy"><div class="eyebrow"><span class="line" aria-hidden="true"></span>一份抽取，一张分布图</div><h1 id="report-title">{question}</h1>{synthetic_badge}<p class="hero-description">从五堆总量到每一张牌，查看这次抽取与预期分布的距离。</p></div><aside class="hero-aside"><span class="aside-index">OBSERVATION / 01</span><p>保留每一次抽取，<br>看见多与少的分布。</p><span class="timestamp">{_esc(_stamp(receipt.get("completed_at")))}</span></aside></section>
<div class="metric-strip" aria-label="本次抽取概要"><div class="metric"><strong>{n:,}<span>次</span></strong><span class="metric-label">固定抽取总数</span></div><div class="metric"><strong>{len(piles)}<span>堆</span></strong><span class="metric-label">每次等概率选堆</span></div><div class="metric"><strong>{total_cards}<span>张</span></strong><span class="metric-label">正逆合并统计牌名</span></div><p class="metric-note">五个位置只表示牌堆归属。<br>位置不赋予时间、主体或因果角色。</p></div>
<section class="pile-section" aria-labelledby="pile-title"><div class="section-heading"><div><span class="section-index">01 / DISTRIBUTION</span><h2 id="pile-title">五堆总览</h2></div><p>{baseline_copy} · 统一次数刻度</p></div><div class="pile-grid">''']
    for pi, pile in enumerate(piles):
        count, exp = _num(pile.get("count")), _num(pile.get("expected"))
        style = _PILE_STYLE.get(str(pile.get("key")), "major")
        delta = count - exp
        direction = "高于" if delta > 0 else "低于" if delta < 0 else "等于"
        parts.append(f'''<button type="button" class="pile-tile {style}" data-pile="{pi}" aria-pressed="false" aria-label="查看{_esc(pile.get('label'))}，{_fmt(count)}次，预期{_fmt(exp)}次"><span class="pile-top"><span class="pile-name"><i aria-hidden="true"></i>{_esc(pile.get('label'))}</span><span class="pile-size">{int(_num(pile.get('size', len(pile.get('cards', [])))))} 张</span></span><span class="pile-count">{_fmt(count)}<small>次</small></span><span class="pile-bar" aria-hidden="true"><span class="pile-fill" style="width:{count / pile_scale * 100:.3f}%"></span><span class="expected-marker" style="left:{exp / pile_scale * 100:.3f}%"></span></span><span class="pile-bottom"><span>{direction}预期 <b>{_fmt(abs(delta))}</b></span><span>{count / n * 100 if n else 0:.1f}%</span></span></button>''')
    parts.append('''</div><p class="section-footnote"><span class="marker-key" aria-hidden="true"></span>竖线 = 预期次数<span class="separator">·</span>点击任一牌堆，查看其中的牌。</p></section>''')
    positive = sorted((c for c in all_cards if c["z"] >= 1), key=lambda c: -c["z"])
    negative = sorted((c for c in all_cards if c["z"] <= -1), key=lambda c: c["z"])
    if positive or negative:
        parts.append('''<section class="standouts" aria-label="相对各自基线的突出偏离">''')
        for direction, candidates, label in (("high", positive, "偏多最突出"), ("low", negative, "偏少最突出")):
            if not candidates:
                continue
            c = candidates[0]
            parts.append(f'''<a class="standout {direction}" href="#card-{c['index']}" data-card-link="{c['index']}"><div class="standout-label"><span class="direction-symbol" aria-hidden="true">{'↗' if direction == 'high' else '↘'}</span><span>{label}<small>按标准化偏离 z 排序</small></span></div><div class="standout-card"><strong>{_esc(c['row'].get('zh', c['row'].get('card_id')))}</strong><span>{_esc(c['pile'].get('label'))} · {_esc(c['element'])}</span></div><div class="standout-value"><strong>{_fmt(c['count'])}<small>次</small></strong><span>预期 {_fmt(c['expected'])} · 差值 {_signed(c['delta'])}</span></div><span class="standout-arrow" aria-hidden="true">→</span></a>''')
        parts.append('</section>')
    parts.append(f'''<section id="explorer" class="explorer" aria-labelledby="explorer-title"><div class="section-heading"><div><span class="section-index">02 / CARD EXPLORER</span><h2 id="explorer-title">逐牌查看</h2></div><p>五堆同时比较，全部 {total_cards} 张牌完整展开。</p></div>
<div class="explorer-surface"><div class="pile-tabs" role="group" aria-label="选择牌堆"><button type="button" class="pile-tab active" data-pile="all" aria-pressed="true">全部牌堆<span>{total_cards}</span></button>''')
    for pi, pile in enumerate(piles):
        style = _PILE_STYLE.get(str(pile.get("key")), "major")
        parts.append(f'''<button type="button" class="pile-tab {style}" data-pile="{pi}" aria-pressed="false"><i aria-hidden="true"></i>{_esc(pile.get('label'))}<span>{len(pile.get('cards', []))}</span></button>''')
    parts.append(f'''</div><div class="filter-toolbar"><div class="band-filters" role="group" aria-label="偏离范围"><button type="button" data-band="deviating" aria-pressed="false">偏离牌<span>{ordinary_count + extreme_count}</span></button><button type="button" data-band="extreme" aria-pressed="false">极端候选<span>{extreme_count}</span></button><button type="button" data-band="all" aria-pressed="true" class="active">全部<span>{total_cards}</span></button></div><div class="search-sort"><label class="search-control"><span class="sr-only">搜索牌名、元素或英文编号</span><svg aria-hidden="true" width="16" height="16" viewBox="0 0 20 20" fill="none"><circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.5"/><path d="m13 13 4 4" stroke="currentColor" stroke-width="1.5"/></svg><input id="card-search" type="search" placeholder="搜索牌名或元素" autocomplete="off"></label><label class="sort-control"><span class="sr-only">卡牌排序</span><select id="card-sort"><option value="abs">偏离程度 ↓</option><option value="high">偏多在前</option><option value="low">偏少在前</option><option value="count">次数从多到少</option><option value="name">按牌名排序</option></select></label></div></div>
<div class="list-context"><p id="result-count" role="status" aria-live="polite">全部 {total_cards} 张牌</p><div class="legend"><span><i class="legend-dot high"></i>偏多</span><span><i class="legend-dot low"></i>偏少</span><span><i class="legend-line"></i>预期</span></div></div><div class="column-head" aria-hidden="true"><span>牌名 / 元素</span><span>实际次数 <small>统一刻度 0–{_fmt(card_scale)}</small></span><span>与预期差值</span><span>偏离分段</span><span></span></div>
<p class="board-hint" id="board-hint">五堆并列展示 · 卡牌条形共用次数刻度 0–{_fmt(card_scale)}<span>屏幕较窄时，可在下方面板内左右滑动。</span></p>
<div id="card-list" class="card-list board" tabindex="0" role="region" aria-label="五堆卡牌并列比较，可横向滚动">''')
    current_group = None
    for c in all_cards:
        row, pile = c["row"], c["pile"]
        if current_group != c["pile_index"]:
            if current_group is not None:
                parts.append('</div><p class="group-empty" hidden>本堆没有符合条件的牌。</p></section>')
            current_group = c["pile_index"]
            style = _PILE_STYLE.get(str(pile.get("key")), "major")
            parts.append(f'''<section class="pile-card-group {style}" data-group="{current_group}" aria-label="{_esc(pile.get('label'))}卡牌"><div class="group-heading"><div><h3><i aria-hidden="true"></i>{_esc(pile.get('label'))}</h3><span class="group-visible-count">{len(pile.get('cards', []))} / {len(pile.get('cards', []))} 张</span></div><p>每张预期 {_fmt(pile.get('card_expected'))} 次</p></div><div class="pile-card-rows">''')
        direction = "high" if c["delta"] > 0 else "low" if c["delta"] < 0 else "neutral"
        pile_style = _PILE_STYLE.get(str(pile.get("key")), "major")
        name = str(row.get("zh") or row.get("card_id") or "未命名牌")
        search = " ".join((name, str(row.get("card_id", "")), c["element"], str(pile.get("label", ""))))
        marker = c["expected"] / card_scale * 100
        width = c["count"] / card_scale * 100
        ztext = _signed(c["z"], 2)
        class_label = _CLASSES.get(str(row.get("class")), "卡牌")
        flag = row.get("holm_flag")
        flag_text = "达到 0.05 阈值" if flag is True else "未达到 0.05 阈值" if flag is False else "未提供阈值标记"
        parts.append(f'''<details id="card-{c['index']}" class="card-row {direction} {c['band_key']}" data-pile-index="{c['pile_index']}" data-band-value="{c['band_key']}" data-z="{c['z']:.15g}" data-count="{c['count']:.15g}" data-order="{c['index']}" data-name="{_esc(name)}" data-search="{_esc(search.lower())}"><summary class="card-summary"><span class="card-identity"><span class="card-name">{_esc(name)}</span><span class="card-sub"><span class="pile-dot {pile_style}" aria-hidden="true"></span>{_esc(pile.get('label'))}<span class="sub-divider">/</span><span title="{_esc(c['element_source'])}">{_esc(c['element'])}</span></span></span><span class="count-cell"><span class="count-track" aria-hidden="true"><span class="count-fill" style="width:{width:.3f}%"></span><span class="expected-marker" style="left:{marker:.3f}%"></span></span><span class="actual-count">{_fmt(c['count'])}<span class="sr-only">次</span></span><span class="expected-copy">预期 {_fmt(c['expected'])}</span></span><span class="delta-cell"><span class="delta-label">差值 </span>{_signed(c['delta'])}<span class="sr-only">次</span></span><span class="band-chip {c['band_key']}">{c['band_label']}</span><span class="expand-icon" aria-hidden="true">+</span><span class="sr-only">，展开统计详情</span></summary><div class="card-detail"><div class="detail-title">统计详情<span>{_esc(class_label)} · 元素来源：{_esc(c['element_source'])}</span></div><dl class="detail-grid"><div><dt>正位 / 逆位</dt><dd>{_fmt(row.get('upright'))}<span> / </span>{_fmt(row.get('reversed'))}</dd></div><div><dt>标准化偏离 z</dt><dd>{ztext}</dd></div><div><dt>精确双尾 p</dt><dd>{_p(row.get('p_two'))}</dd></div><div><dt>Holm 校正 p</dt><dd>{_p(row.get('p_holm'))}</dd><small>{flag_text}</small></div></dl><p class="detail-note">以全部 {n:,} 次抽取为基数：实际 {_fmt(c['count'])} 次，预期 {_fmt(c['expected'], 3)} 次。正逆合并计数；分段只描述偏离大小。</p></div></details>''')
    if current_group is not None:
        parts.append('</div><p class="group-empty" hidden>本堆没有符合条件的牌。</p></section>')
    parts.append(f'''</div><div id="empty-state" class="empty-state" hidden><span aria-hidden="true">⌕</span><h3>没有符合条件的牌</h3><p>试试其他牌名，或查看全部牌堆与分段。</p><button id="reset-filters" type="button">显示全部 {total_cards} 张牌</button></div><noscript><p class="noscript-note">当前浏览器未启用 JavaScript：筛选不生效，全部牌已显示；单牌详情仍可展开。</p></noscript><div class="explorer-footnote"><span><b>普通偏离</b> 1 ≤ |z| &lt; 2 <span class="separator">·</span><b>极端候选</b> |z| ≥ 2</span><span>分段是描述标签，不等同于统计显著。</span></div></div></section>
<section class="method-section" aria-labelledby="method-title"><details class="method-panel"><summary><span><span class="section-index">03 / READING THE NUMBERS</span><h2 id="method-title">这些数字怎么读</h2><span class="method-preview">抽取口径、预期次数、z、p 与 Holm 校正</span></span><span class="method-toggle" aria-hidden="true">+</span></summary><div class="method-content"><div><span class="method-number">01</span><h3>先选堆，再选牌</h3><p>每次先从五堆中等概率选一堆，再从该堆等概率抽一张。每次独立并恢复整副牌，正位与逆位各占 50%。固定 {_fmt(n)} 次，不按结果补抽、重抽或删改。</p><p>每个小牌堆含 14 张，大阿卡那堆含 22 张。五堆机会相同，78 张牌的单牌概率并不相同。</p></div><div><span class="method-number">02</span><h3>预期是一条比较基线</h3><p>每堆预期为总次数 ÷ 5；小牌每张为总次数 ÷ 70，大牌每张为总次数 ÷ 110。{_fmt(n)} 次下，分别约为 {_fmt(n / 70)} 次和 {_fmt(n / 110)} 次。</p><p>卡牌条形使用同一次数刻度，细竖线是该牌的预期次数；差值 = 实际 − 预期。预期并不要求本次结果恰好落在这条线上。</p></div><div><span class="method-number">03</span><h3>z 让不同基线可以比较</h3><p>z =（实际 − 预期）÷ 标准差。正值表示偏多，负值表示偏少。默认完整显示五堆的全部牌；选择「偏离牌」可聚焦普通偏离与极端候选。</p><p>接近基线：|z| &lt; 1；普通偏离：1 ≤ |z| &lt; 2；极端候选：|z| ≥ 2。这些名称描述分布，不直接给出牌义或统计结论。</p></div><div><span class="method-number">04</span><h3>p 与 Holm 是检验注释</h3><p>双尾 p 使用二项分布的精确上下尾（均包含观察值），取较小尾概率的两倍，上限为 1。它描述在此抽取模型下的尾部概率，不表示解读的准确率。</p><p>Holm 按各堆分别校正多重比较，阈值 0.05。它只增加注释，不隐藏任何牌、不改变频数，也不改变偏离分段。</p></div></div></details></section>
</main><footer class="site-footer"><span class="footer-brand">Statistical <em>Tarot</em></span><p>每次抽取有记录，每张牌都可查。</p><span>单文件 · 离线可用</span></footer></div><script>{_JS}</script></body></html>''')
    return "".join(parts)


def write_page(out: Path, stats: dict) -> None:
    """Atomically replace ``page.html`` without following a target link.

    The fixed pending name is exclusively created: an existing file or link
    causes an error, never a truncation. Cleanup touches only our own file.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rendered = render_report(stats)
    pending = out / ".page.html.pending"
    identity = None
    try:
        with pending.open("x", encoding="utf-8", newline="") as stream:
            identity = os.fstat(stream.fileno())
            stream.write(rendered)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, out / "page.html")
    finally:
        if identity is not None:
            try:
                if os.path.samestat(pending.lstat(), identity):
                    pending.unlink()
            except FileNotFoundError:
                pass


_CSS = r'''
:root{--paper:#f7f5f0;--surface:#fffefa;--ink:#282d29;--muted:#73786f;--faint:#90958d;--line:#e5e6dd;--soft:#eeefe7;--high:#ae6244;--high-bg:#f8ede5;--low:#467b88;--low-bg:#eaf1f1;--fire:#b87355;--water:#6a949d;--air:#9b9d72;--earth:#79886a;--major:#9487a5;--focus:#315c4b}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--paper);color:var(--ink);font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei","PingFang SC",sans-serif;-webkit-font-smoothing:antialiased}button,input,select{font:inherit}button,a,input,select,summary{-webkit-tap-highlight-color:transparent}button{color:inherit}a{color:inherit;text-decoration:none}button,summary,select{cursor:pointer}button{border:0;background:none}button:focus-visible,a:focus-visible,summary:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:4px}button:hover,a:hover{transition:background .15s,color .15s}h1,h2,h3,p{margin:0}button,summary{touch-action:manipulation}::selection{background:#dae5d5}details>summary{list-style:none}details>summary::-webkit-details-marker{display:none}[hidden]{display:none!important}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.skip-link{position:fixed;top:12px;left:12px;z-index:100;padding:10px 18px;background:var(--ink);color:white;transform:translateY(-160%)}.skip-link:focus{transform:translateY(0)}
.page-shell{max-width:1248px;margin:auto;padding:0 48px}.site-header{min-height:101px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);gap:20px}.brand{display:flex;align-items:center;gap:11px;font:25px/1 Georgia,"Times New Roman",serif;letter-spacing:-.8px}.brand em,.footer-brand em{font-weight:normal;color:#717c67}.brand-symbol{font:36px/1 Georgia,serif;color:#62795b;padding-bottom:3px}.offline{font-size:11px;letter-spacing:.08em;display:flex;align-items:center;gap:8px;color:var(--muted);white-space:nowrap}.offline i{width:6px;height:6px;border-radius:50%;background:#839572}.hero{display:grid;grid-template-columns:minmax(0,1fr) 239px;gap:56px;padding:57px 0 36px}.eyebrow{display:flex;align-items:center;gap:9px;font-size:11px;color:#6f7d66;letter-spacing:.16em;margin-bottom:18px}.eyebrow .line{width:23px;height:1px;background:#8a9a7c}h1{font-size:clamp(26px,3.2vw,38px);font-weight:600;line-height:1.5;letter-spacing:-.035em;max-width:800px;overflow-wrap:anywhere}.hero-description{margin-top:19px;font-size:13px;color:var(--muted);line-height:1.9}.hero-aside{border-left:1px solid var(--line);padding:7px 0 0 29px;align-self:center}.aside-index{font-size:9px;letter-spacing:.16em;color:var(--faint)}.hero-aside p{font-family:Georgia,"SimSun",serif;font-size:18px;line-height:1.8;color:#6c7863;margin:15px 0 23px}.timestamp{font-size:10px;line-height:1.9;color:var(--faint);display:block;font-variant-numeric:tabular-nums}.metric-strip{display:grid;grid-template-columns:1fr 1fr 1fr 1.75fr;border-bottom:1px solid var(--line);padding:0 0 30px;align-items:center;gap:25px}.metric{padding:0 26px;border-left:1px solid var(--line)}.metric:first-child{padding-left:0;border:0}.metric strong{display:block;font-size:36px;line-height:1.35;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-1.7px}.metric strong span{font-size:11px;font-weight:400;color:var(--muted);margin-left:9px;letter-spacing:0}.metric-label{font-size:11px;color:var(--muted)}.metric-note{font-size:11px;color:var(--muted);line-height:1.95;text-align:right}.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:21px}.section-index{font-size:9px;letter-spacing:.15em;font-weight:600;color:var(--faint);display:block;margin-bottom:7px}h2{font-size:22px;font-weight:600;letter-spacing:-.035em;line-height:1.5}.section-heading>p{color:var(--muted);font-size:11px;padding-bottom:3px}.pile-section{padding-top:36px}.pile-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px}.fire{--pile-color:var(--fire)}.water{--pile-color:var(--water)}.air{--pile-color:var(--air)}.earth{--pile-color:var(--earth)}.major{--pile-color:var(--major)}.pile-tile{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:19px 18px 14px;text-align:left;position:relative;min-width:0;box-shadow:0 3px 6px #25351a02}.pile-tile:hover{background:#fafbf5;border-color:#abb6a0}.pile-tile[aria-pressed=true]{border-color:var(--pile-color);box-shadow:0 0 0 1px var(--pile-color)}.pile-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.pile-name{font-weight:600;font-size:12px;display:flex;align-items:center;gap:7px;white-space:nowrap}.pile-name i,.pile-tab i,.pile-dot{width:6px;height:6px;background:var(--pile-color);border-radius:50%;display:inline-block;flex-shrink:0}.pile-size{font-size:10px;color:var(--faint);white-space:nowrap}.pile-count{display:block;font-size:32px;font-weight:500;line-height:1.3;margin:13px 0 14px;letter-spacing:-1px;font-variant-numeric:tabular-nums}.pile-count small{font-size:10px;color:var(--muted);font-weight:400;letter-spacing:0;margin-left:6px}.pile-bar{display:block;height:6px;background:#eef0e8;border-radius:3px;position:relative}.pile-fill{height:100%;display:block;background:var(--pile-color);opacity:.7;border-radius:3px}.expected-marker{position:absolute;width:1px;top:-3px;bottom:-3px;background:#535d4c;opacity:.85}.pile-bottom{display:flex;align-items:center;justify-content:space-between;margin-top:13px;color:var(--muted);font-size:10px;gap:6px}.pile-bottom b{font-weight:500;color:var(--ink)}.section-footnote{display:flex;align-items:center;gap:6px;color:var(--faint);font-size:10px;padding-top:11px}.marker-key{height:10px;width:1px;background:#535d4c;display:inline-block;margin:0 5px}.separator{color:#a2a798;padding:0 5px}
.standouts{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:27px}.standout{border:1px solid var(--line);border-radius:10px;display:grid;grid-template-columns:1.08fr 1fr auto 12px;gap:10px;align-items:center;padding:20px 18px;background:#f9f6ef;min-width:0}.standout.low{background:#f0f4f1}.standout:hover{border-color:#b5bcae}.standout-label{display:flex;align-items:center;gap:10px;font-size:10px;color:var(--muted);white-space:nowrap}.direction-symbol{font-size:24px;line-height:1;color:var(--high);align-self:flex-start}.standout.low .direction-symbol{color:var(--low)}.standout-label small{display:block;font-size:8px;color:var(--faint);margin-top:4px}.standout-card{min-width:0}.standout-card strong{display:block;font-size:14px;font-weight:600;overflow-wrap:anywhere}.standout-card>span{display:block;font-size:10px;color:var(--muted);margin-top:3px}.standout-value{text-align:right;white-space:nowrap}.standout-value strong{font-size:25px;font-weight:500;letter-spacing:-1px;line-height:1.2;color:var(--high)}.standout.low .standout-value strong{color:var(--low)}.standout-value strong small{font-size:9px;font-weight:400;color:var(--muted);margin-left:4px;letter-spacing:0}.standout-value>span{display:block;font-size:9px;color:var(--muted);margin-top:6px}.standout-arrow{color:var(--faint);font-size:13px;margin-left:3px}
.explorer{padding-top:40px}.explorer-surface{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:clip}.pile-tabs{display:flex;align-items:stretch;gap:8px;border-bottom:1px solid var(--line);padding:0 22px;flex-wrap:wrap}.pile-tab{display:flex;align-items:center;gap:7px;font-size:12px;min-height:58px;padding:4px 12px 0;border-bottom:2px solid transparent;margin-bottom:-1px;color:var(--muted);white-space:nowrap}.pile-tab span{font-size:10px;margin-left:1px;color:var(--faint);font-variant-numeric:tabular-nums}.pile-tab.active{color:var(--ink);border-bottom-color:#65765b;font-weight:600}.pile-tab:hover{color:var(--ink);background:#f7f8f1}.filter-toolbar{display:flex;justify-content:space-between;align-items:center;padding:21px 26px 13px;gap:16px;flex-wrap:wrap}.band-filters{display:flex;background:#f0f1e9;border-radius:7px;padding:3px;gap:2px}.band-filters button{padding:6px 10px;font-size:10px;white-space:nowrap;color:var(--muted);border-radius:5px;min-height:32px}.band-filters button.active{background:var(--surface);box-shadow:0 1px 3px #26301f0e;color:var(--ink)}.band-filters span{font-size:9px;color:var(--faint);margin-left:5px;font-variant-numeric:tabular-nums}.search-sort{display:flex;align-items:center;gap:10px}.search-control{display:flex;align-items:center;border:1px solid var(--line);border-radius:6px;padding:0 10px;gap:7px;color:var(--faint);height:36px;background:#fffefa}.search-control input{width:145px;min-width:0;font-size:11px;color:var(--ink);background:transparent;border:0;outline-offset:8px}.search-control input::placeholder{color:var(--faint)}.sort-control select{font-size:10px;border:1px solid var(--line);height:36px;max-width:150px;border-radius:6px;background:var(--surface);color:var(--muted);padding:0 8px;outline-offset:2px}.list-context{display:flex;align-items:center;justify-content:space-between;padding:6px 27px 16px;gap:10px;font-size:10px;color:var(--muted)}#result-count{font-variant-numeric:tabular-nums}.legend{display:flex;gap:14px;font-size:9px;align-items:center;white-space:nowrap}.legend>span{display:flex;align-items:center;gap:5px}.legend-dot{display:block;width:5px;height:5px;border-radius:50%}.legend-dot.high{background:var(--high)}.legend-dot.low{background:var(--low)}.legend-line{width:1px;height:9px;background:#535d4c;margin:0 2px}.column-head,.card-summary{display:grid;grid-template-columns:minmax(145px,1.15fr) minmax(160px,1.6fr) 107px 96px 14px;gap:24px;align-items:center}.column-head{margin:0 26px;padding:9px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:9px;color:var(--faint)}.column-head small{font-size:8px;margin-left:6px}.column-head>span:nth-child(3){text-align:right}.column-head>span:nth-child(4){text-align:center}.card-list{padding:0 26px}.card-row{border-bottom:1px solid #eeefe7;scroll-margin-top:20px}.card-row:last-child{border-bottom:0}.card-summary{padding:15px 0;position:relative}.card-summary:hover{background:#f8f9f2}.card-name{display:block;font-size:13px;font-weight:500;line-height:1.55;overflow-wrap:anywhere}.card-row.extreme .card-name{font-weight:650}.card-sub{display:flex;align-items:center;gap:5px;flex-wrap:wrap;color:var(--faint);font-size:9px;margin-top:4px;line-height:1.4}.sub-divider{opacity:.55;margin:0 2px}.pile-dot{width:4px;height:4px}.count-cell{display:grid;grid-template-columns:minmax(0,1fr) 24px;column-gap:11px;align-items:center}.count-track{height:7px;border-radius:4px;background:#f0f0e9;position:relative;display:block}.count-fill{height:100%;border-radius:4px;background:#a7aea0;display:block}.high .count-fill{background:#c29679}.low .count-fill{background:#80a5ac}.near .count-fill{background:#bcc2b3}.actual-count{font-size:16px;line-height:1.2;text-align:right;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-.3px}.expected-copy{grid-column:1/-1;font-size:9px;color:var(--faint);line-height:1.2;margin-top:6px}.delta-cell{color:var(--high);text-align:right;font-size:14px;letter-spacing:-.2px;font-variant-numeric:tabular-nums;font-weight:500}.low .delta-cell{color:var(--low)}.near .delta-cell,.neutral .delta-cell{color:var(--muted)}.delta-label{display:none}.band-chip{font-size:9px;border:1px solid #e4e7da;border-radius:4px;padding:3px 6px;text-align:center;color:#77816c;white-space:nowrap;justify-self:center;line-height:1.5}.band-chip.extreme{background:var(--high-bg);border-color:#eedbc8;color:#a46747}.low .band-chip.extreme{background:var(--low-bg);border-color:#d1e1e0;color:var(--low)}.band-chip.near{color:var(--faint);background:#f7f8f2;border-color:#eceee4}.expand-icon{font-size:16px;color:#8d9983;font-weight:300;line-height:1;transition:transform .15s;text-align:center}.card-row[open] .expand-icon{transform:rotate(45deg)}.card-row[open] .card-summary{padding-bottom:13px}.card-detail{background:#f5f6ee;border:1px solid #e8ebdf;border-radius:7px;padding:16px 19px 15px;margin:0 0 15px}.detail-title{display:flex;align-items:center;justify-content:space-between;gap:10px;font-size:10px;font-weight:600;color:#68745e}.detail-title>span{font-size:9px;font-weight:400;line-height:1.7;color:var(--muted)}.detail-grid{display:grid;grid-template-columns:1fr 1fr 1fr 1.4fr;gap:20px;margin:14px 0 11px}.detail-grid>div{min-width:0}.detail-grid dt{font-size:9px;color:var(--muted);margin-bottom:5px}.detail-grid dd{margin:0;font-size:16px;font-variant-numeric:tabular-nums;line-height:1.5;overflow-wrap:anywhere}.detail-grid dd span{color:#a2aa9c;font-size:13px}.detail-grid small{font-size:9px;color:var(--muted);display:block;margin-top:3px}.detail-note{font-size:9px;color:var(--muted);border-top:1px solid #e0e5d7;padding-top:10px;line-height:1.9}.empty-state{text-align:center;padding:46px 20px 50px}.empty-state>span{color:#829573;font-size:35px;line-height:1}.empty-state h3{font-size:16px;font-weight:500;margin-top:12px}.empty-state p{font-size:11px;color:var(--muted);margin:8px 0 19px}.empty-state button{background:#e7ecdf;padding:9px 17px;border-radius:5px;font-size:11px;color:#526448}.explorer-footnote{display:flex;justify-content:space-between;gap:12px;padding:14px 26px 17px;border-top:1px solid var(--line);font-size:9px;color:var(--muted);line-height:1.8}.explorer-footnote b{font-weight:500;color:#6c7764}.noscript-note{padding:15px 26px;color:var(--muted);font-size:11px}
.method-section{margin:30px 0 42px}.method-panel{border:1px solid var(--line);border-radius:10px;background:#f3f3ec}.method-panel>summary{display:flex;align-items:center;justify-content:space-between;padding:23px 27px;gap:15px}.method-panel h2{font-size:17px}.method-panel .section-index{font-size:8px;margin-bottom:5px}.method-preview{font-size:10px;color:var(--muted);margin-top:5px;display:block}.method-toggle{display:flex;width:28px;height:28px;align-items:center;justify-content:center;border:1px solid #dce0d2;border-radius:50%;font-size:18px;font-weight:300;color:#8a977e;transition:transform .15s;flex-shrink:0}.method-panel[open] .method-toggle{transform:rotate(45deg)}.method-content{display:grid;grid-template-columns:1fr 1fr;gap:26px 42px;border-top:1px solid var(--line);margin:0 27px;padding:27px 0}.method-number{font:italic 15px Georgia,serif;color:#9ca68c}.method-content h3{font-size:13px;font-weight:500;margin:6px 0 10px}.method-content p{font-size:11px;color:var(--muted);line-height:1.95;margin-top:8px}.site-footer{display:flex;justify-content:space-between;align-items:center;gap:16px;border-top:1px solid var(--line);padding:25px 0 34px;color:var(--faint);font-size:9px}.footer-brand{font:16px Georgia,serif;letter-spacing:-.5px;color:#66735f}
@media(min-width:1280px){.hero{padding-top:65px;padding-bottom:40px}.metric-strip{padding-bottom:36px}.pile-section{padding-top:40px}}
@media(max-width:1000px){.page-shell{padding:0 30px}.hero{gap:30px;grid-template-columns:minmax(0,1fr) 200px}.hero-aside{padding-left:22px}.metric-strip{gap:10px;grid-template-columns:1fr 1fr 1fr 1.5fr}.metric{padding:0 19px}.pile-grid{gap:8px}.pile-tile{padding:16px 12px 13px}.pile-top{flex-wrap:wrap;gap:5px}.pile-name{font-size:11px}.standout{grid-template-columns:1fr auto 12px;padding:17px 15px;gap:10px}.standout-label{grid-column:1/-1;margin-bottom:3px}.standout-label small{display:inline;margin-left:9px}.direction-symbol{font-size:18px}.standout-card{padding-left:27px}.column-head,.card-summary{gap:17px;grid-template-columns:minmax(110px,1fr) minmax(130px,1.3fr) 83px 76px 12px}.pile-tabs{gap:4px;padding:0 16px}.pile-tab{padding:3px 9px 0;font-size:11px}.filter-toolbar{padding:19px 22px 13px;gap:12px}.search-control input{width:125px}.search-sort{gap:7px}.column-head{margin:0 22px}.card-list{padding:0 22px}.list-context{padding-left:22px;padding-right:22px}.column-head small{display:block;margin-left:0}.explorer-footnote{padding-left:22px;padding-right:22px;flex-wrap:wrap}.site-footer p{display:none}}
@media(max-width:720px){.page-shell{padding:0 22px}.site-header{min-height:81px}.brand{font-size:23px}.brand-symbol{font-size:32px}.offline{font-size:9px;letter-spacing:0;gap:6px}.hero{grid-template-columns:1fr;padding:35px 0 24px;gap:0}.hero-aside{display:none}.eyebrow{font-size:10px;margin-bottom:14px}h1{font-size:28px;line-height:1.55;letter-spacing:-.035em}.hero-description{font-size:11px;margin-top:15px;max-width:90%}.metric-strip{grid-template-columns:repeat(3,minmax(0,1fr));row-gap:19px;padding-bottom:21px}.metric{padding:0 13px}.metric strong{font-size:31px}.metric strong span{margin-left:5px;font-size:10px}.metric-label{font-size:9px;white-space:nowrap}.metric-note{grid-column:1/-1;text-align:left;font-size:10px;padding:11px 13px;background:#edefe4;border-radius:5px;line-height:1.8}.metric-note br{display:none}.section-heading{align-items:flex-start;flex-direction:column;gap:8px;margin-bottom:17px}.section-index{font-size:8px;margin-bottom:5px}h2{font-size:20px}.section-heading>p{font-size:10px;padding:0}.pile-section{padding-top:27px}.pile-grid{grid-template-columns:repeat(6,minmax(0,1fr));gap:8px}.pile-tile{grid-column:span 2;padding:14px 11px 12px;border-radius:8px}.pile-tile:nth-child(n+4){grid-column:span 3}.pile-top{flex-wrap:wrap;gap:3px}.pile-name{font-size:11px;gap:6px}.pile-size{font-size:8px}.pile-count{font-size:28px;margin:10px 0 13px}.pile-bottom{font-size:9px;flex-wrap:wrap;row-gap:2px;column-gap:3px;margin-top:11px}.section-footnote{font-size:9px;flex-wrap:wrap;gap:3px;padding-top:11px}.standouts{gap:9px;margin-top:22px}.standout{padding:14px 12px 13px;grid-template-columns:1fr auto;gap:9px;border-radius:8px}.standout-label{font-size:9px;gap:5px;margin:0;line-height:1.4;align-items:flex-start}.direction-symbol{font-size:17px}.standout-label small{display:block;font-size:7px;margin:4px 0 0;letter-spacing:0}.standout-card{grid-column:1/-1;padding:3px 0 0}.standout-card strong{font-size:13px}.standout-card>span{font-size:9px;margin-top:3px}.standout-value{text-align:left;grid-column:1}.standout-value strong{font-size:23px}.standout-value>span{font-size:8px;margin-top:3px;white-space:normal;line-height:1.6}.standout-arrow{align-self:end;font-size:15px}.explorer{padding-top:29px}.explorer-surface{border-radius:9px}.pile-tabs{padding:8px 11px 0;gap:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr))}.pile-tab{min-height:42px;justify-content:center;padding:0 4px;font-size:10px;gap:4px}.pile-tab span{font-size:8px}.pile-tab i{width:4px;height:4px}.filter-toolbar{padding:14px 13px 9px;gap:11px;display:block}.band-filters{width:fit-content;max-width:100%;margin-bottom:12px;gap:0}.band-filters button{font-size:9px;padding:5px 8px;min-height:32px}.band-filters span{font-size:8px;margin-left:4px}.search-sort{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px}.search-control{padding:0 8px;min-width:0;height:36px;gap:5px}.search-control svg{width:13px;flex-shrink:0}.search-control input{width:100%;font-size:10px}.sort-control select{font-size:9px;max-width:116px;padding:0 5px;height:36px}.list-context{padding:5px 14px 12px;align-items:center;gap:8px;font-size:9px}.legend{font-size:8px;gap:7px}.legend>span{gap:4px}.legend-dot{width:4px;height:4px}.column-head{display:none}.card-list{padding:0 14px;border-top:1px solid var(--line)}.card-summary{grid-template-columns:minmax(0,1fr) 56px 14px;gap:8px 12px;padding:14px 0 13px}.card-identity{grid-column:1;grid-row:1}.card-name{font-size:13px;line-height:1.5}.card-sub{font-size:8px;margin-top:4px;gap:4px}.count-cell{grid-row:2;grid-column:1/-1;grid-template-columns:minmax(0,1fr) 24px;column-gap:12px;margin-top:4px}.actual-count{font-size:15px}.count-track{height:6px}.expected-copy{font-size:8px;margin-top:5px}.delta-cell{grid-column:2;grid-row:1;align-self:start;font-size:13px;padding-top:1px}.delta-label{font-size:8px;display:block;color:var(--faint);font-weight:400;line-height:1.6}.band-chip{grid-column:1;grid-row:3;justify-self:start;font-size:8px;padding:2px 5px;margin-top:1px}.expand-icon{grid-column:3;grid-row:1;align-self:center;font-size:16px}.card-summary>.sr-only{grid-column:1}.card-detail{padding:13px 12px;margin-bottom:13px}.detail-title{display:block;font-size:10px}.detail-title>span{display:block;font-size:8px;margin-top:4px}.detail-grid{grid-template-columns:1fr 1fr;gap:14px 15px;margin:13px 0 11px}.detail-grid dt{font-size:8px}.detail-grid dd{font-size:15px}.detail-grid small{font-size:8px}.detail-note{font-size:8px;line-height:1.9}.explorer-footnote{padding:12px 14px 14px;font-size:8px;gap:5px;display:block}.explorer-footnote>span{display:block}.explorer-footnote>span+span{margin-top:4px}.explorer-footnote .separator{padding:0 3px}.empty-state{padding:32px 18px}.empty-state h3{font-size:14px}.empty-state p{font-size:10px}.empty-state button{font-size:10px}.method-section{margin:23px 0 28px}.method-panel>summary{padding:20px 18px}.method-panel h2{font-size:16px}.method-preview{font-size:9px}.method-panel .section-index{font-size:7px}.method-content{grid-template-columns:1fr;margin:0 18px;gap:20px;padding:20px 0}.method-content h3{font-size:12px}.method-content p{font-size:10px;line-height:2}.method-number{font-size:14px}.site-footer{padding:22px 0 28px;gap:8px;font-size:8px;align-items:center}.footer-brand{font-size:15px}.noscript-note{font-size:10px;padding:12px 14px}}
/* Reading text stays readable at normal zoom; labels may wrap instead of shrinking. */
.offline,.timestamp,.metric-label,.metric-note,.section-heading>p,.pile-name,.pile-size,.pile-bottom,.section-footnote,.standout-label,.standout-label small,.standout-card>span,.standout-value>span,.pile-tab span,.band-filters span,.list-context,.legend,.column-head,.column-head small,.card-sub,.expected-copy,.band-chip,.detail-title>span,.detail-grid dt,.detail-grid small,.detail-note,.explorer-footnote,.method-preview,.site-footer{font-size:11px}
.hero-description{font-size:14px}.pile-name,.pile-tab,.band-filters button,.search-control input,.sort-control select,.detail-title,.method-content p,.empty-state p,.empty-state button{font-size:12px}
.card-name{font-size:14px}.standout-card strong{font-size:15px}.detail-note{font-size:12px;line-height:1.9}.detail-grid dt{font-size:12px}.detail-grid dd{font-size:17px}.standout-label{white-space:normal}.standout-label small{line-height:1.6}.standout-value>span{white-space:normal;line-height:1.6}.standout-value strong small,.pile-count small,.metric strong span{font-size:11px}.metric-label{white-space:normal}.method-content h3{font-size:14px}.noscript-note{font-size:12px}
@media(max-width:1000px){.standout-label small{display:block;margin-left:0}.standout{grid-template-columns:1fr auto 12px}.standout-card{padding-left:0}.standout-value{max-width:170px}.column-head,.card-summary{column-gap:14px}}
@media(max-width:720px){.hero-description{font-size:12px;max-width:none}.metric-label,.metric-note,.section-heading>p,.pile-size,.pile-bottom,.section-footnote,.standout-label small,.standout-card>span,.standout-value>span,.pile-tab span,.band-filters span,.list-context,.legend,.card-sub,.expected-copy,.band-chip,.detail-title>span,.detail-grid small,.method-preview,.site-footer,.explorer-footnote{font-size:11px}.pile-name,.pile-tab,.band-filters button,.search-control input,.sort-control select,.standout-label,.detail-title,.detail-grid dt,.detail-note,.method-content p,.empty-state p,.empty-state button{font-size:12px}.card-name{font-size:14px}.standout-card strong{font-size:14px}.standout{grid-template-columns:1fr auto;padding:15px 12px}.standout-value{max-width:none}.standout-label{align-items:flex-start}.standout-label small{margin-top:6px}.standout-label .direction-symbol{margin-top:2px}.pile-tab{min-height:48px}.band-filters button{padding:7px 8px;min-height:36px}.search-control,.sort-control select{height:40px}.search-control{padding:0 8px}.sort-control select{max-width:133px}.search-sort{gap:6px}.list-context{align-items:flex-start;flex-wrap:wrap;gap:8px;padding-top:8px}.legend{gap:10px}.column-head,.card-summary{column-gap:12px}.card-summary{padding-top:17px;padding-bottom:17px;row-gap:10px}.card-sub{line-height:1.6}.delta-label{font-size:11px}.delta-cell{font-size:15px}.actual-count{font-size:17px}.expected-copy{margin-top:8px}.band-chip{padding:3px 6px}.detail-grid dd{font-size:17px}.detail-grid{gap:17px 12px}.explorer-footnote>span+span{margin-top:8px}.method-content h3{font-size:14px}.method-content p{line-height:1.9}.site-footer{flex-wrap:wrap}.offline{font-size:11px;letter-spacing:0}.brand{font-size:21px}.brand-symbol{font-size:29px}.method-preview{line-height:1.7}.metric strong span{font-size:11px}}
/* The all-piles view preserves five simultaneous, independently sorted columns. */
.synthetic-tag{display:inline-block;margin-top:13px;padding:4px 9px;border:1px solid #dbe2cd;border-radius:4px;color:#637453;background:#edf1e4;font-size:11px;letter-spacing:.04em}.page-shell{max-width:1464px}.brand{white-space:nowrap}.board-hint{font-size:11px;color:var(--muted);padding:0 26px 14px;line-height:1.8}.board-hint>span{display:none;margin-top:2px;color:var(--faint)}
.pile-card-group{min-width:0}.group-heading{padding:17px 0 15px;border-bottom:1px solid var(--line)}.group-heading>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.group-heading h3{display:flex;align-items:center;gap:7px;font-size:14px;font-weight:600}.group-heading h3 i{width:6px;height:6px;background:var(--pile-color);border-radius:50%;flex-shrink:0}.group-visible-count{font-size:11px;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}.group-heading p{font-size:11px;color:var(--muted);margin-top:6px}.group-empty{font-size:12px;line-height:1.9;text-align:center;color:var(--muted);padding:28px 12px;min-height:100px}
.card-list.board{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));align-items:start;padding:0;border-top:1px solid var(--line);overflow-x:auto;overscroll-behavior-x:contain;scrollbar-color:#b9c3ad #f0f2e8;scrollbar-width:thin}.board .pile-card-group{border-right:1px solid var(--line);height:100%;padding:0 15px}.board .pile-card-group:last-child{border-right:0}.board .group-heading{margin:0 -15px;padding:16px 15px 14px;background:#f7f8f1;border-top:3px solid var(--pile-color);min-height:85px}.board .group-heading>div{flex-wrap:wrap;gap:4px 8px}.board .group-heading h3{font-size:13px}.board .card-summary{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px 8px;padding:16px 0}.board .card-identity{grid-row:1;grid-column:1/-1;padding-right:17px}.board .card-name{font-size:14px;font-weight:550}.board .card-sub{font-size:11px;line-height:1.6;margin-top:5px}.board .expand-icon{grid-column:2;grid-row:1;align-self:start;font-size:17px;padding-top:3px}.board .count-cell{grid-row:2;grid-column:1/-1;grid-template-columns:minmax(0,1fr) 24px;gap:0 9px;margin-top:2px}.board .count-track{height:6px}.board .actual-count{font-size:17px}.board .expected-copy{font-size:11px;margin-top:6px}.board .delta-cell{grid-row:3;grid-column:1;text-align:left;font-size:13px;align-self:center;padding:0}.board .delta-label{display:inline;font-size:11px;color:var(--muted);margin-right:3px}.board .band-chip{grid-row:3;grid-column:2;justify-self:end;font-size:11px;padding:2px 5px;line-height:1.6;margin:0}.board .card-detail{padding:13px 11px;margin-bottom:14px}.board .detail-title{display:block;font-size:12px}.board .detail-title>span{display:block;line-height:1.8;margin-top:5px;font-size:11px;overflow-wrap:anywhere}.board .detail-grid{grid-template-columns:1fr 1fr;gap:15px 8px}.board .detail-grid dt{font-size:11px}.board .detail-grid dd{font-size:15px}.board .detail-grid small{font-size:11px;line-height:1.7}.board .detail-note{font-size:11px;line-height:1.9}
@media(max-width:1100px){.card-list.board{grid-template-columns:repeat(5,minmax(210px,1fr))}.board-hint>span{display:block}}
@media(max-width:720px){.board-hint{padding:0 14px 14px;font-size:11px}.card-list.board{grid-template-columns:repeat(5,240px);padding:0;scroll-snap-type:x proximity}.board .pile-card-group{scroll-snap-align:start;padding:0 15px}.board .card-summary{padding:17px 0}.board .group-heading h3{font-size:14px}.board .group-heading{min-height:88px}.board .card-sub,.board .expected-copy,.board .band-chip,.board .delta-label{font-size:11px}.board .card-name{font-size:14px}.board .actual-count{font-size:17px}.board .card-detail{padding:13px 11px}.board .detail-note{font-size:12px}.brand{font-size:19px;gap:7px}.brand-symbol{font-size:26px}.offline{font-size:10px}.metric strong{white-space:nowrap;font-size:29px;letter-spacing:-1px}.metric{padding:0 9px}.metric strong span{margin-left:4px}.metric-label{font-size:11px}.metric-note{font-size:11px}}
@media print{.card-list.board{overflow:visible;grid-template-columns:repeat(5,minmax(0,1fr))}.board-hint>span{display:none}.board .pile-card-group{padding:0 8px}.board .group-heading{margin:0 -8px;padding-left:8px;padding-right:8px}.board .card-summary{break-inside:avoid}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{transition:none!important;animation:none!important}}
@media print{body{background:white}.page-shell{padding:0;max-width:none}.site-header{min-height:55px}.hero{padding-top:25px}.skip-link,.filter-toolbar,.pile-tabs,.expand-icon,.method-toggle,.offline,.standout-arrow{display:none!important}.hero-aside{display:none}.hero{grid-template-columns:1fr}.card-row[hidden]{display:block!important}.card-summary{break-inside:avoid}.card-row{break-inside:avoid}.explorer-surface{overflow:visible}.pile-tile,.standout{box-shadow:none}.site-footer{padding:15px 0}.method-section{margin-bottom:20px}.section-heading{break-after:avoid}.card-detail{break-inside:avoid}.pile-grid{break-inside:avoid}}
'''


_JS = r'''
(() => {
  'use strict';
  const list = document.getElementById('card-list');
  const rows = Array.from(list.querySelectorAll('.card-row'));
  const groups = Array.from(list.querySelectorAll('.pile-card-group'));
  const search = document.getElementById('card-search');
  const sort = document.getElementById('card-sort');
  const status = document.getElementById('result-count');
  const empty = document.getElementById('empty-state');
  let pile = 'all';
  let band = 'all';
  const pileButtons = Array.from(document.querySelectorAll('button[data-pile]'));
  const bandButtons = Array.from(document.querySelectorAll('button[data-band]'));
  const collator = new Intl.Collator('zh-CN', {numeric: true});
  function update() {
    const query = search.value.trim().toLocaleLowerCase();
    const ranked = rows.slice().sort((a, b) => {
      const az = Number(a.dataset.z), bz = Number(b.dataset.z);
      let result = 0;
      if (sort.value === 'high') result = bz - az;
      else if (sort.value === 'low') result = az - bz;
      else if (sort.value === 'count') result = Number(b.dataset.count) - Number(a.dataset.count);
      else if (sort.value === 'name') result = collator.compare(a.dataset.name, b.dataset.name);
      else result = Math.abs(bz) - Math.abs(az);
      return result || Number(a.dataset.order) - Number(b.dataset.order);
    });
    let count = 0;
    const fragments = new Map(groups.map(group => [group.dataset.group, document.createDocumentFragment()]));
    const visibleCounts = new Map(groups.map(group => [group.dataset.group, 0]));
    ranked.forEach(row => {
      const inPile = pile === 'all' || row.dataset.pileIndex === pile;
      const inBand = band === 'all' || (band === 'extreme' ? row.dataset.bandValue === 'extreme' : row.dataset.bandValue !== 'near');
      const inSearch = !query || row.dataset.search.includes(query);
      row.hidden = !(inPile && inBand && inSearch);
      if (!row.hidden) {
        count += 1;
        visibleCounts.set(row.dataset.pileIndex, visibleCounts.get(row.dataset.pileIndex) + 1);
      }
      fragments.get(row.dataset.pileIndex).appendChild(row);
    });
    groups.forEach(group => {
      const key = group.dataset.group;
      const visible = visibleCounts.get(key);
      group.hidden = pile !== 'all' && key !== pile;
      group.querySelector('.pile-card-rows').appendChild(fragments.get(key));
      group.querySelector('.group-visible-count').textContent = visible + ' / ' + group.querySelectorAll('.card-row').length + ' 张';
      group.querySelector('.group-empty').hidden = visible !== 0;
    });
    list.classList.toggle('board', pile === 'all');
    document.querySelector('.column-head').hidden = pile === 'all';
    document.getElementById('board-hint').hidden = pile !== 'all';
    list.setAttribute('aria-label', pile === 'all' ? '五堆卡牌并列比较，可横向滚动' : '当前牌堆的全部匹配卡牌');
    status.textContent = '显示 ' + count + ' / ' + rows.length + ' 张牌';
    empty.hidden = count !== 0;
    pileButtons.forEach(button => {
      const active = button.dataset.pile === pile;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('active', active);
    });
    bandButtons.forEach(button => {
      const active = button.dataset.band === band;
      button.setAttribute('aria-pressed', String(active));
      button.classList.toggle('active', active);
    });
  }
  pileButtons.forEach(button => button.addEventListener('click', () => {
    pile = button.dataset.pile;
    update();
    if (button.classList.contains('pile-tile')) {
      document.getElementById('explorer').scrollIntoView({block:'start'});
      const target = document.querySelector('.pile-tab[data-pile="' + pile + '"]');
      if (target) target.focus({preventScroll:true});
    }
  }));
  bandButtons.forEach(button => button.addEventListener('click', () => { band = button.dataset.band; update(); }));
  search.addEventListener('input', update);
  sort.addEventListener('change', update);
  document.getElementById('reset-filters').addEventListener('click', () => {
    pile = 'all'; band = 'all'; search.value = ''; update();
    document.querySelector('[data-band="all"]').focus({preventScroll:true});
  });
  document.querySelectorAll('[data-card-link]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault();
    pile = 'all'; band = 'all'; search.value = ''; update();
    const row = document.getElementById('card-' + link.dataset.cardLink);
    if (row) {
      row.open = true;
      row.scrollIntoView({block:'center'});
      row.querySelector('summary').focus({preventScroll:true});
    }
  }));
  update();
})();
'''
