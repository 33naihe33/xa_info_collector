# 调整实施计划：数据源扩充 + 9条线 + 去图谱 + 条线卡片UI

> 日期：2026-07-13

## 四项调整

### 调整1：扩充5个网页数据源

新增5个 adapter（继承 BaseAdapter）：
- 人民雄安网 www.rmxiongan.com
- 长城新媒体雄安频道 xiongan.hebccw.cn
- 容城县政府 www.hbrc.gov.cn
- 雄县政府 www.xiongxian.gov.cn
- 安新县政府 www.anxin.gov.cn

每个 adapter 实现 fetch_list + fetch_detail，在 sources.yaml 配置。先用通用 HTML adapter 处理（政府站/媒体站结构类似），按实际页面结构调整选择器。

### 调整2：9条线 + 关键词事件语义分析

完全重写 opp_rules.yaml 为9条线，judge_opportunity.txt 重写，rule_filter 更新预筛词。
9条线：corporate / cross_border / inclusive / retail / operations / fintech / synergy / risk_control / digital_currency

### 调整3：去掉关系图谱

删除 GraphView.vue、/graph 路由、侧边栏菜单项。保留后端 /api/graph 和 entities/relations 抽取。

### 调整4：条线卡片入口

商机页面改为：首页展示9个条线卡片（含条线名+图标+商机数），点击进入该条线的商机列表。
