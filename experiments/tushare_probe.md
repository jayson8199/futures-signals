# tushare 数据包期货接口探测

- 时间：2026-10-15 15:17（UTC）
- 服务器：https://tl.kaixin8.top/tushare/sdk

| 接口 | 状态 | 行数 | 最早 | 最晚 | 字段 / 报错 |
|---|---|---|---|---|---|
| fut_basic DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=93c017d21e224f92be8f520b702f3572 |
| fut_basic CZCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=a47c1333ad1b4fb8be212801db9194e8 |
| fut_basic SHFE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=e1186644623e4eeb8d997c896e5004ff |
| fut_basic CFFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=c0c3750d442248af8826a6c4ca5801c2 |
| fut_basic GFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=d7dc0a3b0d704bba8e8fd4d61e4439c6 |
| fut_basic INE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=699283bc6acf4882a9d44fc27d5ada66 |
| fut_daily P.DCE | 通 | 2000 | 20180716 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily PL.DCE | 通 | 2000 | 20180713 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P9999.DCE | 错 | 0 |  |  | [upstream_pool_exhausted] 数据当前不可用，请稍后重试；建议等待30秒后重试；request_id=4614d5254d9b44aea82c09244e76b4f1 |
| fut_daily P8888.DCE | 错 | 0 |  |  | [upstream_pool_exhausted] 数据当前不可用，请稍后重试；建议等待30秒后重试；request_id=b01301c6132e4cab82e70aa22fc8e3a9 |
| fut_daily P2601.DCE | 通 | 243 | 20250116 | 20260116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1701.DCE | 通 | 244 | 20160118 | 20170116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1501.DCE | 通 | 245 | 20140116 | 20150116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1201.DCE | 通 | 244 | 20110118 | 20120117 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P0901.DCE | 通 | 246 | 20080116 | 20090116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_mapping P.DCE | 通 | 4609 | 20071029 | 20261016 | ts_code,trade_date,mapping_ts_code |
| fut_holding P 20261014 | 通 | 4000 | 20261014 | 20261014 | trade_date,symbol,broker,vol,vol_chg,long_hld,long_chg,short_hld,short_chg |
| fut_wsr P 20261014 | 通 | 3 | 20261014 | 20261014 | trade_date,symbol,fut_name,warehouse,pre_vol,vol,vol_chg,unit |
| fut_settle P2601.DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=4727343ceb3646cda6fe7463755f601a |
| fut_weekly_detail P | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=2c7d6f2618af478cb6baf16c795d713e |

- 拉取阶段出错：[invalid_params] 业务参数缺失或格式不合法；request_id=705aa7db6b2847fc82ec4dd97b7c0d2a
