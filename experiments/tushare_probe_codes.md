# 代码格式探测

| 接口 | 状态 | 行数 | 最早 | 最晚 | 字段 / 报错 |
|---|---|---|---|---|---|
| fut_basic exchange only | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=fb8946331e0f4b4987dea9f623b6802b |
| fut_basic +fields | 通 | 3286 | 19990104 | 20261008 | ts_code,symbol,name,list_date,delist_date |
| fut_basic fut_code | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=63496771f9e9463aaab7de78a622ab31 |
| fut_basic no args | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=9c11c2fe0e1e427da61787fe5c813529 |
| fut_basic fut_type=2 | 错 | 0 |  |  | [invalid_params] 业务参数缺失或格式不合法；request_id=be58a6108b914b078685e91b9fcd4631 |
| fut_daily trade_date DCE | 通 | 302 | 20261014 | 20261014 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
| fut_daily trade_date only | 通 | 1017 | 20261014 | 20261014 | ts_code,trade_date,pre_close,pre_settle,open,high,low,close,settle,change1,change2,vol… |
