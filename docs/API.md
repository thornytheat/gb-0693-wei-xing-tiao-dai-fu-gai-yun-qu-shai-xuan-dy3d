# 接口

`POST /api/run`：JSON中的csv文本，省略使用样例；或multipart字段file。最大5MB。成功提交同时登记为一版目录修订并切为当前版；目录切换失败时批次仍保存，响应带`warning`，页面继续显示上一版目录。

`POST /api/m1`至`POST /api/m8`：独立运行到指定模块，JSON结构同运行接口。`/api/m8`为采购对账。

`GET /api/history`：历史批次。`POST /api/review`接收id、revision和decision（通过或退回）。`GET /api/evidence.csv`提供单一证据导出。

结构错误422，版本变化409，文件过大413；错误返回code与message。所有页面可从左侧八个模块入口访问。

`GET /api/runs/<id>`读取指定批次；页面与证据CSV通过run_id查询参数绑定批次，模块导航保留该参数。

JSON请求体必须是对象，数组、标量、null、损坏JSON及错误上传字段返回400，且不运行默认样例。

## 目录修订

`GET /api/catalogues`列出修订（seq、digest、active、identity）。`GET /api/catalogues/active`返回当前修订。`POST /api/catalogues/switch`接收`id`或`run_id`，原子切换当前修订；修订不存在返回404且保留原修订，页面仍显示上一版。

## 合同与付款（本地台账）

`POST /api/contracts`登记合同，接受单对象或`{"contracts":[...]}`，字段contract_no/合同号、scene/场景号、price/价格、signed_at、catalogue_id、note。同号同内容重复提交返回原记录（reused），同号不同内容返回409，已签合同不可改写。`GET /api/contracts[?scene=]`、`GET /api/contracts/<id或合同号>`。`POST /api/contracts/import`接受`{"csv":...}`批量导入。

`POST /api/payments`登记付款（contract_no/合同号、amount/金额、paid_at、note），只追加并按合同号+金额+时间+备注幂等。`GET /api/payments[?contract=]`、`POST /api/payments/import`。

`POST /api/commit`接收`run_id`，按该批次当前目录计划生成新合同；批次号即幂等键，重试不新增合同。

`GET /api/reconciliation[?run_id=]`输出计划、合同、付款与编号对照。

合同原号始终按签约时号码保存；对账通过当前目录身份映射解析出当前编号，不改写历史。
