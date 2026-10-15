# tushare 数据包期货接口探测

- 时间：2026-10-15 16:28（UTC）
- 服务器：https://tl.kaixin8.top/tushare/sdk

| 接口 | 状态 | 行数 | 最早 | 最晚 | 字段 / 报错 |
|---|---|---|---|---|---|
| fut_basic DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=5b589b7fc95149ab816345fe2cead9a9 |
| fut_basic CZCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=b2005fca80f7465e90b13ea387fa31d9 |
| fut_basic SHFE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=d80bd63dd68a4c0d85b5a2f7947ff38f |
| fut_basic CFFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=8212e16f878846eebca9a8c7564cce36 |
| fut_basic GFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=f90f202f312f41018c61524dee09539b |
| fut_basic INE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=68aa46defeb84509b4d10fd431a3e47b |
| fut_daily P.DCE | 通 | 2000 | 20180716 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily PL.DCE | 通 | 2000 | 20180713 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P9999.DCE | 空 | 0 |  |  |  |
| fut_daily P8888.DCE | 错 | 0 |  |  | [upstream_pool_exhausted] 数据当前不可用，请稍后重试；建议等待30秒后重试；request_id=ff98da6d7492418ab4d4903fab19b708 |
| fut_daily P2601.DCE | 通 | 243 | 20250116 | 20260116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1701.DCE | 通 | 244 | 20160118 | 20170116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1501.DCE | 通 | 245 | 20140116 | 20150116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1201.DCE | 通 | 244 | 20110118 | 20120117 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P0901.DCE | 通 | 246 | 20080116 | 20090116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_mapping P.DCE | 通 | 4609 | 20071029 | 20261016 | ts_code,trade_date,mapping_ts_code |
| fut_holding P 20261014 | 错 | 0 |  |  | ('Connection aborted.', RemoteDisconnected('Remote end closed connection without response')) |
| fut_wsr P 20261014 | 通 | 3 | 20261014 | 20261014 | trade_date,symbol,fut_name,warehouse,pre_vol,vol,vol_chg,unit |
| fut_settle P2601.DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=d67507744b694e4b9f8b14047e699869 |
| fut_weekly_detail P | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=c944dbc475bb4862a7bc2a9deb68b042 |
- P2710.DCE 拉取失败：P2710.DCE 多次失败
- P2711.DCE 拉取失败：P2711.DCE 多次失败
- P2712.DCE 拉取失败：P2712.DCE 多次失败

## 棕榈油全合约拉取：237/240 个合约
- 加权指数 data/weighted_tushare/P0.csv：4563 行，2008-01-02 ~ 2026-10-15
- 与新浪版加权对比（1642 个共同交易日）：平均相对误差 0.002%
