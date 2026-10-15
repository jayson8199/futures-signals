# tushare 数据包期货接口探测

- 时间：2026-10-15 15:28（UTC）
- 服务器：https://tl.kaixin8.top/tushare/sdk

| 接口 | 状态 | 行数 | 最早 | 最晚 | 字段 / 报错 |
|---|---|---|---|---|---|
| fut_basic DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=55110c367b944324b6b2440c3acb3463 |
| fut_basic CZCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=89dd94705e04470b887d9f8122341436 |
| fut_basic SHFE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=1b09ef1190ba4e058648f6d720554a06 |
| fut_basic CFFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=ed85b464054344e2aba632c9a098eebe |
| fut_basic GFEX | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=3518c95b7f1d43a296bd5363d94c3398 |
| fut_basic INE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=042d7e5c9e14456bb4cebacae25cab29 |
| fut_daily P.DCE | 通 | 2000 | 20180716 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily PL.DCE | 通 | 2000 | 20180713 | 20261015 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P9999.DCE | 错 | 0 |  |  | [upstream_pool_exhausted] 数据当前不可用，请稍后重试；建议等待30秒后重试；request_id=dfdd8438ce96487bb23808e3b5e5a2c3 |
| fut_daily P8888.DCE | 错 | 0 |  |  | [upstream_pool_exhausted] 数据当前不可用，请稍后重试；建议等待30秒后重试；request_id=69eb199d315a44db8b09eed4be2fed67 |
| fut_daily P2601.DCE | 通 | 243 | 20250116 | 20260116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1701.DCE | 通 | 244 | 20160118 | 20170116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1501.DCE | 通 | 245 | 20140116 | 20150116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P1201.DCE | 通 | 244 | 20110118 | 20120117 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily P0901.DCE | 通 | 246 | 20080116 | 20090116 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_mapping P.DCE | 通 | 4609 | 20071029 | 20261016 | ts_code,trade_date,mapping_ts_code |
| fut_holding P 20261014 | 错 | 0 |  |  | HTTPSConnectionPool(host='tl.kaixin8.top', port=443): Read timed out. |
| fut_wsr P 20261014 | 通 | 3 | 20261014 | 20261014 | trade_date,symbol,fut_name,warehouse,pre_vol,vol,vol_chg,unit |
| fut_settle P2601.DCE | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=322e84e948964fb69e89f7556113bc74 |
| fut_weekly_detail P | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=ccfa6e616c5f4b948301d4f4c173151e |
