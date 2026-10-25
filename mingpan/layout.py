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


def card(date, a, level, gist, yi, ji, good_hours, direction, tip):
    color = STAR_COLOR[a["stars"]]
    stars = "★" * a["stars"] + "☆" * (5 - a["stars"])
    rows = [("宜", "；".join(yi[:2])), ("忌", "；".join(ji[:2])),
            ("好时辰", "、".join(good_hours[:2]) or "今天没有特别好的时辰，稳着来"),
            ("贵人方位", direction)]
    body = "".join(
        f'<tr><td style="padding:4px 10px 4px 0;color:#888;white-space:nowrap;vertical-align:top">{esc(k)}</td>'
        f'<td style="padding:4px 0;color:#222">{esc(v)}</td></tr>' for k, v in rows)
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


def wuxing_bars(weight, xi, ji):
    top = max(3.0, max(weight.values()))
    rows = []
    for wx in "木火土金水":
        w = weight[wx]
        tag = "喜" if wx in xi else "忌" if wx in ji else ""
        tag_color = "#27ae60" if tag == "喜" else "#c0392b"
        pct = round(w / top * 100)
        rows.append(
            f'<tr><td style="width:22px;font-size:14px;color:{WX_COLOR[wx]};font-weight:bold">{wx}</td>'
            f'<td style="width:22px;font-size:12px;color:{tag_color}">{tag}</td>'
            f'<td><div style="background:#f0f0f0;border-radius:4px;height:12px">'
            f'<div style="background:{WX_COLOR[wx]};width:{pct}%;height:12px;border-radius:4px"></div></div></td>'
            f'<td style="width:34px;text-align:right;font-size:12px;color:#888">{w:.1f}</td></tr>')
    return ('<div style="margin:0 0 14px"><div style="font-size:15px;font-weight:bold;margin-bottom:6px">'
            '今天流日带来的五行</div>'
            f'<table style="width:100%;border-collapse:separate;border-spacing:0 4px">{"".join(rows)}</table>'
            '<div style="font-size:12px;color:#888">喜用多是助力，忌神多是消耗；含三合、三会成局的加成。</div></div>')


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


def page(card_html, bars_html, cal_html, details_html):
    return ('<div style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
            'max-width:560px;margin:0 auto;padding:4px;color:#222;background:#fafafa">'
            f'{card_html}{bars_html}{cal_html}'
            '<div style="font-size:15px;font-weight:bold;margin:18px 0 4px;padding-top:10px;border-top:1px solid #ddd">'
            '详细分析</div>'
            f'{details_html}</div>')
