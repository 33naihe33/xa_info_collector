# 模拟 datasource JSON 响应
SAMPLE_DATASOURCE_JSON = {
    "publishDomain": "https://www.xiongan.gov.cn",
    "isAbsolutePath": 0,
    "datasource": [
        {
            "title": "张国华调研重点项目",
            "publishUrl": "../20260710/abc123/c.html",
            "publishTime": "2026-07-10 09:14:40",
            "sourceText": "雄安发布",
            "summary": "推进重点项目建设",
            "keywords": "调研,项目",
            "contentType": "MultiMedia",
            "contentId": "20260710abc123",
        },
        {
            "title": "外链跳转文章",
            "publishUrl": "https://news.cn/some/external",
            "publishTime": "2026-07-09 10:00:00",
            "sourceText": "新华网",
            "summary": "",
            "contentType": "Link",
            "contentId": "external001",
        },
    ],
}

# 模拟详情页 HTML
SAMPLE_DETAIL_HTML = """
<html><head>
<meta name="source" content="雄安发布">
<meta name="publishdate" content="2026-07-10">
</head><body>
<div id="detail" class="detail">
  <h1 class="title">张国华调研重点项目</h1>
  <div id="detailContent" class="detail-content">
    <p>&emsp;&emsp;7月10日，张国华深入启动区调研重点项目建设工作。</p>
    <p>&emsp;&emsp;调研组先后实地察看了多个项目现场。</p>
  </div>
  <div class="author">责任编辑： 张三</div>
</div>
</body></html>
"""


# ====================================================================
# 人民雄安网 (rmxiongan) 样本
# ====================================================================
RMXIONGAN_LIST_HTML = """
<html><body>
<div class="pageContent">
  <dl class="clearfix">
    <dt><img src="/img/a.jpg"></dt>
    <dd>
      <h3><a href="/n2/2026/0713/c383557-41637328.html">容西片区安置房交付</a></h3>
      <p class="summary">容西片区安置房交付工作稳步推进。</p>
      <p class="time"><b id="newstime">2026年07月13日10:34</b></p>
    </dd>
  </dl>
  <dl class="clearfix">
    <dd>
      <h3><a href="/n2/2026/0709/c383557-41637300.html">启动区基础设施进展</a></h3>
      <p class="time"><b id="newstime">2026年07月09日08:00</b></p>
    </dd>
  </dl>
  <dl class="clearfix">
    <dd><h3><a href="/n2/2026/0701/c383557-41637000.html">旧条目</a></h3></dd>
  </dl>
</div>
</body></html>
"""

RMXIONGAN_DETAIL_HTML = """
<html><head>
<title>容西片区安置房交付--人民雄安网</title>
<meta name="description" content="7月13日，容西片区首批安置房正式交付。">
</head><body>
<div id="rm_txt_zw">
  <p>&emsp;&emsp;7月13日，容西片区首批安置房正式交付使用。</p>
  <p>&emsp;&emsp;本次交付涵盖多个回迁小区，配套学校、医院同步启用。</p>
</div>
<b id="newstime">2026年07月13日10:34</b>
</body></html>
"""


# ====================================================================
# 长城新媒体雄安频道 (hebccw) 样本
# ====================================================================
HEBCCW_LIST_HTML = """
<html><body>
<div class="centerLeft">
  <div class="centerLeftLi">
    <a href="/system/2026/07/13/123456789.shtml">
      <span class="centerTitle">雄安站迎来暑运高峰</span>
      <span class="centerTime"><span>2026-07-13 13:07:49</span></span>
    </a>
  </div>
  <div class="centerLeftLi">
    <a href="/system/2026/07/09/123456788.shtml">
      <span class="centerTitle">白洋淀生态治理见成效</span>
      <span class="centerTime"><span>2026-07-09 09:00:00</span></span>
    </a>
  </div>
</div>
</body></html>
"""

HEBCCW_DETAIL_HTML = """
<html><head><title>雄安站迎来暑运高峰</title></head><body>
<div class="detailTitle"><span>雄安站迎来暑运高峰</span></div>
<div class="detailMessage">
  <p>7月13日，雄安站迎来暑运首个客流高峰。</p>
  <p>当日发送旅客突破3万人次，列车班次加密运行。</p>
</div>
</body></html>
"""


# ====================================================================
# 容城县政府 (rongcheng_gov) 样本
# ====================================================================
RONGCHENG_LIST_HTML = """
<html><body>
<ul class="xxgk-list">
  <li class="xxgk-comm-line">
    <a href="/news/00-80-67-1-10/10001.html">容城县召开第N次常务会议</a>
    <span style="float:right">2026-07-10</span>
  </li>
  <li class="xxgk-comm-line">
    <a href="/news/00-80-67-1-10/10000.html">容城县2026年民生实事进展</a>
    <span style="float:right">2026-07-05</span>
  </li>
</ul>
</body></html>
"""

RONGCHENG_DETAIL_HTML = """
<html><head><title>容城县召开第N次常务会议</title></head><body>
<div class="cont_title">容城县召开第N次常务会议</div>
<div class="rq">2026-07-10</div>
<div class="con" id="content">
  <p>7月10日上午，容城县召开常务会议，研究部署下半年重点工作。</p>
  <p>会议审议通过多项工作方案。</p>
</div>
</body></html>
"""


# ====================================================================
# 雄县政府 (xiongxian_gov) 样本（注意：无前导斜杠的详情URL）
# ====================================================================
XIONGXIAN_LIST_HTML = """
<html><head><meta charset="utf-8"></head><body>
<table class="list">
  <tr>
    <td><a href="content-173-99001.html">雄县召开乡村振兴推进会</a></td>
    <td>2026-07-08</td>
  </tr>
  <tr>
    <td><a href="content-173-99000.html">雄县招商引资签约</a></td>
    <td>2026-07-01</td>
  </tr>
</table>
</body></html>
"""

XIONGXIAN_DETAIL_HTML = """
<html><head><meta charset="utf-8"><title>雄县召开乡村振兴推进会</title></head><body>
<table class="sj_bt"><tr><td>雄县召开乡村振兴推进会</td></tr></table>
<table class="sj_nr"><tr><td>
  <p>7月8日，雄县召开乡村振兴工作推进会。</p>
  <p>会议强调要加快推进农村人居环境整治。</p>
</td></tr></table>
<div class="fbtime">发布时间：2026-07-08</div>
</body></html>
"""


# ====================================================================
# 安新县政府 (anxin_gov) 样本
# ====================================================================
ANXIN_LIST_HTML = """
<html><body>
<ul class="xxgk-list">
  <li class="xxgk-comm-line">
    <a href="/news/00-80-67-1-3/20001.html">安新县推进白洋淀旅游升级</a>
    <span class="fr">2026-07-09</span>
  </li>
  <li class="xxgk-comm-line">
    <a href="/news/00-80-67-1-3/20000.html">安新县防汛工作部署</a>
    <span class="fr">2026-07-03</span>
  </li>
</ul>
</body></html>
"""

ANXIN_DETAIL_HTML = """
<html><head><title>安新县推进白洋淀旅游升级</title></head><body>
<input type="hidden" name="ArticleTitle" value="安新县推进白洋淀旅游升级">
<div class="info">发布时间：2026-07-09</div>
<div id="conN">
  <p>7月9日，安新县召开白洋淀旅游升级专题会议。</p>
  <p>重点推进景区基础设施改造和服务品质提升。</p>
</div>
</body></html>
"""
