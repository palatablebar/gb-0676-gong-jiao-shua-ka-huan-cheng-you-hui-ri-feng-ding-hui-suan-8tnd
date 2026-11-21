# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive导出一份带清单、站点依据与每卡当日应收的证据CSV。

`GET /api/stations`返回当前生效站点资料、切换历史与类型标签；`POST /api/stations`接收version、limits(`normal`/`hub` 分钟)与stations，先整体校验再原子切换，失败返回422且旧资料与旧日账不变；同版本不同内容返回409；相同内容重复切换幂等。`GET /api/receivables`返回到当前为止的卡日额度占用，重跑同一批次不会新增占用。依据未核清（`UNVERIFIED_BASIS`）时复核封存返回409。
