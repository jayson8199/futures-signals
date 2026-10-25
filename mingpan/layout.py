#!/usr/bin/env python3
"""
命盘日报的 HTML 版面：最上面一张结论卡片，接着五行强弱条和七天星级日历，详细分析放在最后。
邮件和微信（PushPlus html 模板）共用同一份 HTML，样式全部写在行内，兼容邮件客户端。
"""
import html

WX_COLOR = {"木": "#3a8f5c", "火": "#d9534f", "土": "#b8862b", "金": "#9a8a5a", "水": "#2f6db5"}
STAR_COLOR = {1: "#c0392b", 2: "#e67e22", 3: "#7f8c8d", 4: "#27ae60", 5: "#1e8449"}
WEEK = "一二三四五六日"


def esc(s):
    return html.escape(str(s))


def card(date, a, level, gist, domains, ji, good_hours, bad_hours, direction, tip, month_line):
    """domains：[(领域, 建议, 理由, 补充)]，卡片里只放建议和第一条补充，理由留在详细分析。"""
    color = STAR_COLOR[a["stars"]]
    stars = "★" * a["stars"] + "☆" * (5 - a["stars"])
    rows = [("本月", month_line)]
    rows += [(k, text + (f"；{more[0]}" if more else "")) for k, text, why, more in domains]
    rows += [("忌", "；".join(ji[:2])),
            ("好时辰", good_hours[:3] or "今天白天没有特别好的时辰，稳着来"),
            ("避开", bad_hours[:2] or "今天白天没有特别要避开的时辰"),
            ("贵人方位", direction)]
    body = "".join(
        f'<tr><td style="padding:4px 10px 4px 0;color:#888;white-space:nowrap;vertical-align:top">{esc(k)}</td>'
        f'<td style="padding:4px 0;color:#222">{"<br>".join(map(esc, v)) if isinstance(v, list) else esc(v)}</td></tr>'
        for k, v in rows)
    return (
        f'<div style="border:1px solid #e5e5e5;border-left:6px solid {color};border-radius:10px;'
        f'padding:14px 16px;margin:0 0 14px;background:#fff">'
        f'<div style="font-size:13px;color:#888">{date.month}/{date.day} 周{WEEK[date.weekday()]} · '
        f'{esc(a["month_gz"])}月 {esc(a["day_gz"])}日</div>'
        f'<div style="font-size:24px;color:{color};margin:6px 0 2px;letter-spacing:2px">{stars} '
        f'<span style="font-size:17px;letter-spacing:0">{esc(level)}</span></div>'
        f'<div style="font-size:15px;color:#222;font-weight:bold;margin:6px 0 10px">{esc(gist)}</div>'
        f'<table style="border-collapse:collapse;font-size:14px;line-height:1.5">{body}</table>'
        f'<div style="font-size:13px;color:#555;margin-top:10px;padding-top:8px;border-top:1px dashed #ddd">'
        f'提醒：{esc(tip)}</div></div>')


def wuxing_bars(view):
    """view：{"喜": [...], "忌": [...]}，每项含 wx、w、group、mean，忌神有分量时另含 use、fix。"""
    top = max(3.0, max(i["w"] for k in view for i in view[k]))
    blocks = []
    for kind, color, head in (("喜", "#27ae60", "喜用：帮你的"), ("忌", "#c0392b", "忌神：耗你的，也能用")):
        total = sum(i["w"] for i in view[kind])
        rows = []
        for i in view[kind]:
            pct = round(i["w"] / top * 100)
            rows.append(
                f'<tr><td style="width:22px;font-size:14px;color:{WX_COLOR[i["wx"]]};font-weight:bold">{i["wx"]}</td>'
                f'<td style="width:96px;font-size:12px;color:#666">{esc(i["group"])} · {esc(i["mean"])}</td>'
                f'<td><div style="background:#f0f0f0;border-radius:4px;height:12px">'
                f'<div style="background:{WX_COLOR[i["wx"]]};width:{pct}%;height:12px;border-radius:4px"></div></div></td>'
                f'<td style="width:34px;text-align:right;font-size:12px;color:#888">{i["w"]:.1f}</td></tr>')
            if i.get("use"):
                rows.append(
                    f'<tr><td></td><td colspan="3" style="font-size:12px;color:#444;line-height:1.5;padding:0 0 6px">'
                    f'<b>用好它：</b>{esc(i["use"])}。<br><b>化解：</b>{esc(i["fix"])}。</td></tr>')
        blocks.append(
            f'<div style="font-size:13px;color:{color};font-weight:bold;margin:8px 0 2px">{head}'
            f'<span style="font-weight:normal;color:#888">（今天合计 {total:.1f}）</span></div>'
            f'<table style="width:100%;border-collapse:separate;border-spacing:0 4px">{"".join(rows)}</table>')
    return ('<div style="margin:0 0 14px"><div style="font-size:15px;font-weight:bold;margin-bottom:2px">'
            '今天流日带来的五行</div>' + "".join(blocks) +
            '<div style="font-size:12px;color:#888">数字是分量，含三合、三会成局的加成；没来的五行是 0。</div></div>')


def week_calendar(days):
    cells = []
    for i, (d, b) in enumerate(days):
        color = STAR_COLOR[b["stars"]]
        border = "2px solid #333" if i == 0 else "1px solid #e5e5e5"
        cells.append(
            f'<td style="text-align:center;padding:6px 2px;border:{border};border-radius:6px;background:#fff">'
            f'<div style="font-size:11px;color:#888">{"今天" if i == 0 else "周" + WEEK[d.weekday()]}</div>'
            f'<div style="font-size:11px;color:#888">{d.month}/{d.day}</div>'
            f'<div style="font-size:13px;color:#222;margin:2px 0">{esc(b["day_gz"])}</div>'
            f'<div style="font-size:12px;color:#fff;background:{color};border-radius:10px;'
            f'padding:1px 0;margin:0 3px">{b["stars"]}★</div></td>')
    return ('<div style="margin:0 0 14px"><div style="font-size:15px;font-weight:bold;margin-bottom:6px">'
            '七天星级</div>'
            '<table style="width:100%;border-collapse:separate;border-spacing:3px;table-layout:fixed">'
            f'<tr>{"".join(cells)}</tr></table></div>')


def month_calendar(month_days, today):
    """整月日历，每天按星级上色，今天加框。"""
    head = "".join(f'<td style="text-align:center;font-size:11px;color:#888">{w}</td>' for w in WEEK)
    cells = ['<td></td>'] * month_days[0][0].weekday()
    for d, b in month_days:
        color = STAR_COLOR[b["stars"]]
        border = "2px solid #222" if d == today else "2px solid transparent"
        fade = "opacity:0.45;" if d < today else ""
        cells.append(f'<td style="text-align:center;padding:0"><div style="background:{color};color:#fff;'
                     f'border:{border};border-radius:6px;font-size:12px;line-height:26px;{fade}">{d.day}</div></td>')
    cells += ['<td></td>'] * (-len(cells) % 7)
    rows = "".join("<tr>" + "".join(cells[i:i + 7]) + "</tr>" for i in range(0, len(cells), 7))
    legend = " ".join(f'<span style="display:inline-block;width:10px;height:10px;border-radius:2px;'
                      f'background:{STAR_COLOR[n]};margin:0 2px 0 6px"></span>{n}★' for n in range(1, 6))
    return ('<div style="margin:0 0 14px"><div style="font-size:15px;font-weight:bold;margin-bottom:6px">'
            f'{today.month}月星级日历</div>'
            '<table style="width:100%;border-collapse:separate;border-spacing:3px;table-layout:fixed">'
            f'<tr>{head}</tr>{rows}</table>'
            f'<div style="font-size:11px;color:#888;margin-top:2px">{legend}</div></div>')


def page(card_html, bars_html, cal_html, details_html):
    return ('<div style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
            'max-width:560px;margin:0 auto;padding:4px;color:#222;background:#fafafa">'
            f'{card_html}{bars_html}{cal_html}'
            '<div style="font-size:15px;font-weight:bold;margin:18px 0 4px;padding-top:10px;border-top:1px solid #ddd">'
            '详细分析</div>'
            f'{details_html}</div>')
