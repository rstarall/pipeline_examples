import http.client
import json

conn = http.client.HTTPSConnection("google.serper.dev")
payload = json.dumps({
  "q": "表面活性剂毒性wiki"
})
headers = {
  'X-API-KEY': 'b981da4c22e8e472ff3840e9e975b5b9827f8795',
  'Content-Type': 'application/json'
}
conn.request("POST", "/search", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))

"""
返回结构:
{
  "searchParameters": {
    "q": "表面活性剂毒性wiki",
    "type": "search",
    "engine": "google"
  },
  "organic": [
    {
      "title": "表面活性剂- 维基百科，自由的百科全书",
      "link": "https://zh.wikipedia.org/zh-hans/%E8%A1%A8%E9%9D%A2%E6%B4%BB%E6%80%A7%E5%89%82",
      "snippet": "表面活性剂又称界面活性剂，是能使目标溶液表面张力显著下降的物质，可降低两种液体或液体-固体间的表面张力。种类繁多。最典型的例子是肥皂，具分解、渗入的效果，应用 ...",
      "position": 1
    },
    {
      "title": "苯扎氯铵- 维基百科，自由的百科全书",
      "link": "https://zh.wikipedia.org/zh-hans/%E8%8B%AF%E6%89%8E%E6%B0%AF%E9%93%B5",
      "snippet": "苯扎氯铵是滴眼剂经常使用的消毒剂：典型的浓度范围为0.004％至0.01％。更强的浓度可产生腐蚀性，导致角膜内皮不可逆转的损害。 苯扎氯铵也具有表面活性剂的 ...",
      "position": 2
    },
    {
      "title": "生物表面活性剂_百度百科",
      "link": "https://baike.baidu.com/item/%E7%94%9F%E7%89%A9%E8%A1%A8%E9%9D%A2%E6%B4%BB%E6%80%A7%E5%89%82/1917410",
      "snippet": "... 毒性低，与人体和环境相容性好，具有良好的乳化、分散、增溶等特性，在石油钻采等领域具有研究和开发价值，已应用于石油工业。生物表面活性剂是微生物在一定条件下代谢 ...",
      "position": 3
    },
    {
      "title": "表面活性剂 - MBA智库百科",
      "link": "https://wiki.mbalib.com/wiki/%E8%A1%A8%E9%9D%A2%E6%B4%BB%E6%80%A7%E5%89%82",
      "snippet": "两性表面活性剂以其独特的多功能性著称，主要特性有：①低毒性和对皮肤、眼睛的低刺激性；②极好的耐硬水性和耐高浓度电解质性，甚至在海水中也可以有效地使用；③良好的生物降解性 ...",
      "position": 4
    },
    {
      "title": "表面活性剂污染_百度百科",
      "link": "https://baike.baidu.com/item/%E8%A1%A8%E9%9D%A2%E6%B4%BB%E6%80%A7%E5%89%82%E6%B1%A1%E6%9F%93/8573136",
      "snippet": "表面活性剂污染是指含有亲水基团和憎水基团的界面活性物质因不合理排放导致的环境问题，其按离子性可分为阴离子型、阳离子型、非离子型及两性表面活性剂四种类型。",
      "position": 5
    },
    {
      "title": "非离子型表面活性剂 - MBA智库百科",
      "link": "https://wiki.mbalib.com/wiki/%E9%9D%9E%E7%A6%BB%E5%AD%90%E5%9E%8B%E8%A1%A8%E9%9D%A2%E6%B4%BB%E6%80%A7%E5%89%82",
      "snippet": "试验表明，甾醇类表面活性剂毒性低，可用于医药领域。 各类与人体接触配方中表面活性剂的毒副作用研究受到关注。表面活性剂的发展更倾向于安全无污染、生物降解完全 ...",
      "position": 6
    },
    {
      "title": "分散剂和表面活性剂之间的区别",
      "link": "http://www.ccia-cleaning.org/content/m_details_34_35304.html",
      "snippet": "分散剂和表面活性剂之间的主要区别在于，分散剂可改善悬浮液中的颗粒分离，而表面活性剂是可降低物质两相之间表面张力的物质。 分散剂是表面活性剂的一 ...",
      "date": "Jan 4, 2021",
      "position": 7
    },
    {
      "title": "两性离子表面活性剂_百度百科",
      "link": "http://sgj.nc.gov.cn/ncdoc/ncscjdj/uploadfile/k5embr04pqh",
      "snippet": "具有高效、无毒、低刺激性、且有优良生物降解特性。 两性离子表面活性剂功能介绍. 编辑. 两性离子聚丙烯酰胺因分子内含阳离子基和 ...",
      "date": "Dec 5, 2015",
      "position": 8
    },
    {
      "title": "脂肪醇小百科：用途、益处以及它们在日常产品中的重要性",
      "link": "https://www.goldenagri.com.sg/cn/fatty-alcohols-101-their-uses-and-benefits-in-everyday-products/",
      "snippet": "“您可能听过这样的传言：'醇类对皮肤有害'，甚至'所有醇类都会让皮肤变干'。 ... 这也使它们成为生产日用品（洗涤剂、沐浴液和牙膏等）所使用的表面活性剂的理想 ...",
      "date": "May 7, 2025",
      "position": 9
    },
    {
      "title": "环氧化合物-公卫百科-公共卫生科学数据中心",
      "link": "https://www.phsciencedata.cn/Share/wiki/wikiView?id=8d360f57-f8f8-4f87-a08b-1f3bc77b8696",
      "snippet": "工业上用作表面活性剂、溶剂、粘合剂、合成树脂，也用作熏蒸杀虫和杀菌剂。并可作为增塑剂、稳定剂、纺织品处理剂、涂料等。 在生产环境中对人体的 ...",
      "date": "Jan 6, 2013",
      "position": 10
    }
  ],
  "relatedSearches": [
    {
      "query": "活化剂是什么"
    },
    {
      "query": "苯扎氯铵和酒精的区别"
    },
    {
      "query": "苯扎氯銨安全嗎"
    },
    {
      "query": "苄索氯铵"
    },
    {
      "query": "苯扎氯铵用途"
    },
    {
      "query": "苯扎氯铵真菌"
    },
    {
      "query": "苯扎氯铵宠物"
    },
    {
      "query": "苯扎氯铵是防腐剂吗"
    },
    {
      "query": "苯扎氯铵消毒"
    },
    {
      "query": "Benzalkonium chloride"
    }
  ],
  "credits": 1
}
"""