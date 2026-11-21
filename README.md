# 公交刷卡换乘优惠与日封顶回算

供公交清分中心复核员核对原始记录、处理差异并封存证据。

## 启动

```sh
docker compose up --build -d
docker compose exec -T app pytest -q
```

打开 http://localhost:18245 。首次进入自动运行仓内脏样例。工具条可重跑、切换样例或上传CSV。SQLite保存在命名卷records中，重建服务保留批次。

## 模块

- 1. 刷卡采信：`/taps`，`/api/taps`。
- 2. 线路换乘：`/routes`，`/api/routes`。
- 3. 票价版本：`/fares`，`/api/fares`。
- 4. 行程配对：`/journeys`，`/api/journeys`。
- 5. 优惠回算：`/discounts`，`/api/discounts`。
- 6. 清分对账：`/clearing`，`/api/clearing`。
- 7. 日结归档：`/settlement`，`/api/settlement`。

## 核心规则

换乘按上次有效付费行程的时间窗计算，时限由换乘涉及的站点类型裁决：普通站 60 分钟、枢纽站（机场/火车站）90 分钟，两程中任一站为枢纽即按枢纽时限，半开区间、恰好截止点排除。因此 75 分钟的枢纽联程能享受优惠，而普通站的 75 分钟换乘仍被排除；不做全城统一放宽，避免短途行程不断续优惠。

优惠与日封顶按确定顺序裁决并保留分币守恒：先扣换乘优惠，再对卡号业务日施加封顶。每张卡每个业务日形成唯一应收（`card|business_day`），重跑同一批不重复占用额度。

复核页面沿换乘逐程展示站点依据、适用时限、间隔与日终封顶额度；站点资料切换失败时旧版资料与旧版日账保持完整；换乘依据未核清前不能封存。

## 演示

1. 打开首页，核对当次计算、差异和隔离原因。
2. 切换模块查看源行及裁决依据；优惠回算页沿换乘查看站点依据、适用时限与当日应收。
3. 重跑相同样例，批次号、行数与额度占用保持一致。
4. 站点资料在优惠回算页切换；校验失败时旧资料与旧日账不变。
5. 依据未核清时封存被拒；核清后复核并导出一份证据CSV。版本已变化的复核提交返回409。

## 输入与输出

输入列见 `docs/DATA-DICTIONARY.md`。项目包含dirty.csv、clean.csv、legacy.csv、hub.csv，统一走实际导入路径。上传限制4MB，拒绝不带时区的时间。业务键按字符串保留，Decimal参与计算，空值不会当零。

`POST /api/runs` 接收sample或csv；`GET /api/runs`返回历史批次；`POST /api/runs/<id>/review`需要version与decision；`GET /api/runs/<id>/archive`返回唯一证据导出。`GET|POST /api/stations` 查看或切换站点资料，`GET /api/receivables` 查看卡日额度占用。

## 范围

样例均为虚构。单机复核工具不连接生产系统；不提供登录、远端数据库或自动支付。内存计算按4MB输入上限控制，SQLite事务保证结果完整写入。

## 目录

app为服务与规则，sample_data为输入，tests为测试，docs为定义与深度登记。
