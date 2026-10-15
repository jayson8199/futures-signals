#!/usr/bin/env python3
"""
期货关键事件日历（引爆点预警）
数据来源：固定日程事件（可靠、离线可用）
- 每周固定：API/EIA 原油库存、Mysteel 钢材库存、初请失业金
- 每月固定：非农（首个周五）、财新PMI、LPR、官方PMI（月末）
- 2026 年硬编码日期：FOMC 议息（来源：美联储官网）
"""

from datetime import datetime, timedelta

# 品种名称（用于显示）
SYM_NAMES = {
    'SC0': '原油', 'FU0': '燃料油', 'LU0': '低硫燃料油', 'BU0': '沥青', 'PG0': '液化石油气',
    'TA0': 'PTA', 'PX0': '对二甲苯', 'MA0': '甲醇', 'EG0': '乙二醇', 'PF0': '短纤',
    'RB0': '螺纹钢', 'HC0': '热轧卷板', 'I0': '铁矿石', 'J0': '焦炭', 'JM0': '焦煤',
    'SF0': '硅铁', 'SM0': '锰硅', 'FG0': '玻璃',
    'AU0': '黄金', 'AG0': '白银', 'CU0': '沪铜', 'AL0': '沪铝',
    'M0': '豆粕', 'Y0': '豆油', 'P0': '棕榈油', 'OI0': '菜油', 'RM0': '菜粕', 'C0': '玉米',
    'IF0': '沪深300', 'IH0': '上证50', 'IC0': '中证500', 'IM0': '中证1000',
}

# 2026 年 FOMC 议息（决策日，北京时间次日凌晨 02:00 公布）
# 来源：美联储官网 2026 年会议日历；带 * 为季度会议（含点阵图 SEP）
FOMC_2026 = {
    '2026-01-28': False, '2026-03-18': True, '2026-04-29': False, '2026-06-17': True,
    '2026-07-29': False, '2026-09-16': True, '2026-10-28': False, '2026-12-09': True,
}

# 每周固定事件（0=周一 ... 6=周日）
WEEKLY_EVENTS = {
    2: [  # 周三
        {'time': '04:30', 'name': 'API 原油库存', 'imp': 1,
         'syms': ['SC0', 'FU0', 'LU0', 'BU0', 'PG0']},
        {'time': '22:30', 'name': 'EIA 原油库存', 'imp': 3,
         'syms': ['SC0', 'FU0', 'LU0', 'BU0', 'PG0', 'TA0', 'PX0', 'MA0']},
    ],
    3: [  # 周四
        {'time': '09:00起', 'name': '我的钢铁(Mysteel)钢材库存产量周报', 'imp': 2,
         'syms': ['RB0', 'HC0', 'I0']},
        {'time': '20:30', 'name': '美国初请失业金人数', 'imp': 1,
         'syms': ['AU0', 'AG0', 'CU0', 'IF0']},
    ],
}

# 每月固定事件规则
def monthly_events(d: datetime):
    """返回某日的月度固定事件列表"""
    evts = []
    day = d.day
    wd = d.weekday()

    # 每月第一个周五：美国非农就业
    if wd == 4 and day <= 7:
        evts.append({'time': '20:30', 'name': '美国非农就业报告', 'imp': 3,
                     'syms': ['AU0', 'AG0', 'CU0', 'IF0', 'IH0']})

    # 财新中国 PMI
    if day == 1:
        evts.append({'time': '09:45', 'name': '财新中国制造业PMI', 'imp': 1,
                     'syms': ['RB0', 'HC0', 'CU0', 'IF0']})
    if day == 3:
        evts.append({'time': '09:45', 'name': '财新中国服务业PMI', 'imp': 1,
                     'syms': ['IF0', 'IC0']})

    # LPR 报价
    if day == 20:
        evts.append({'time': '09:15', 'name': 'LPR 贷款市场报价利率', 'imp': 2,
                     'syms': ['IF0', 'IH0', 'IC0', 'IM0', 'RB0']})

    # 官方制造业 PMI（每月最后一个日历日 09:30）
    tomorrow = d + timedelta(days=1)
    if tomorrow.month != d.month:
        evts.append({'time': '09:30', 'name': '中国官方制造业PMI', 'imp': 2,
                     'syms': ['RB0', 'HC0', 'I0', 'CU0', 'IF0']})

    # FOMC 议息（北京时间次日凌晨 02:00 公布利率决议）
    ds = d.strftime('%Y-%m-%d')
    if ds in FOMC_2026:
        sep = FOMC_2026[ds]
        name = '美联储 FOMC 利率决议' + ('（季度会议·含点阵图）' if sep else '')
        evts.append({'time': '02:00(次日凌晨)', 'name': name, 'imp': 3,
                     'syms': ['AU0', 'AG0', 'CU0', 'IF0', 'IH0', 'IC0', 'IM0']})

    return evts


def get_events(date_str: str):
    """获取某日全部事件，按重要性排序"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    evts = list(WEEKLY_EVENTS.get(d.weekday(), [])) + monthly_events(d)
    # 未来日期可能不在 FOMC 表中（跨年），忽略
    for e in evts:
        e['impact'] = '、'.join(SYM_NAMES.get(s, s) for s in e['syms'])
    evts.sort(key=lambda x: -x['imp'])
    return evts


def get_monthly_notes(date_str: str):
    """按日期所在旬返回中旬/上旬宏观事件提醒"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    day = d.day
    notes = []
    if 5 <= day <= 13:
        notes.append('本月中上旬：美国 CPI、中国 CPI/PPI 即将公布（具体日期待定），'
                     '注意宏观数据落地带来的波动（影响黄金、白银、有色、股指）')
    if 10 <= day <= 14:
        notes.append('USDA 月度供需报告（WASDE）通常在每月 12 日前后公布，'
                     '影响豆粕、油脂、玉米等农产品')
    return notes


def get_upcoming(date_str: str, days: int = 7):
    """未来 N 天内的重要事件（仅 ★★★ 级）"""
    d = datetime.strptime(date_str, '%Y-%m-%d')
    out = []
    for i in range(1, days + 1):
        nd = (d + timedelta(days=i)).strftime('%Y-%m-%d')
        for e in get_events(nd):
            if e['imp'] >= 3:
                out.append({'date': nd, **e})
    return out


if __name__ == '__main__':
    # 自测
    for ds in ['2026-09-09', '2026-09-10', '2026-09-16']:
        print(f'=== {ds} ===')
        for e in get_events(ds):
            print(f"  {'★' * e['imp']} {e['time']} {e['name']} → 影响: {e['impact']}")
    print('=== 未来7天 ★★★ ===')
    for e in get_upcoming('2026-09-09'):
        print(f"  {e['date']} {e['time']} {e['name']}")
    print('=== 月度提醒 ===')
    for n in get_monthly_notes('2026-09-09'):
        print(f'  · {n}')
