"""
1.关键词搜索链接
https://api.openalex.org/keywords?search=artificial%20intelligence
返回:
{"meta":{"count":5,"db_response_time_ms":16,"page":1,"per_page":25,"groups_count":null},"results":[{"id":"https://openalex.org/keywords/artificial-intelligences","display_name":"Artificial Intelligences","relevance_score":22.127735,"works_count":0,"cited_by_count":0,"works_api_url":"https://api.openalex.org/works?filter=keywords.id:keywords/artificial-intelligences","updated_date":"2024-05-31T07:44:15.476701","created_date":"2024-04-10"},{"id":"https://openalex.org/keywords/anticipation","display_name":"Anticipation (artificial intelligence)","relevance_score":18.355133,"works_count":0,"cited_by_count":0,"works_api_url":"https://api.openalex.org/works?filter=keywords.id:keywords/anticipation","updated_date":"2024-08-12T23:26:20.126546","created_date":"2024-08-07"},{"id":"https://openalex.org/keywords/artificial-intelligence-technology","display_name":"Artificial Intelligence Technology","relevance_score":18.355133,"works_count":0,"cited_by_count":0,"works_api_url":"https://api.openalex.org/works?filter=keywords.id:keywords/artificial-intelligence-technology","updated_date":"2024-05-31T08:14:11.957472","created_date":"2024-04-10"},{"id":"https://openalex.org/keywords/symbolic-artificial-intelligence","display_name":"Symbolic artificial intelligence","relevance_score":18.355133,"works_count":0,"cited_by_count":0,"works_api_url":"https://api.openalex.org/works?filter=keywords.id:keywords/symbolic-artificial-intelligence","updated_date":"2024-08-12T23:48:20.499502","created_date":"2024-08-07"},{"id":"https://openalex.org/keywords/artificial-general-intelligence","display_name":"Artificial General Intelligence","relevance_score":6.118377,"works_count":0,"cited_by_count":0,"works_api_url":"https://api.openalex.org/works?filter=keywords.id:keywords/artificial-general-intelligence","updated_date":"2024-05-31T08:20:11.951121","created_date":"2024-04-10"}],"group_by":[]}
"""
"""
2.使用works_api_url获取详细文章的json
https://api.openalex.org/works?filter=keywords.id:keywords/symbolic-artificial-intelligence
返回:

"""