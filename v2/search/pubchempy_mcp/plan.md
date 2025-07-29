根据这些教程和文档(可以额外联网搜索):
https://pubchempy.readthedocs.io/en/latest/guide/searching.html
https://zhuanlan.zhihu.com/p/644492173
https://blog.csdn.net/gouyue777/article/details/143579589
https://zhuanlan.zhihu.com/p/352707632
编写一个使用pubchempy和mcp库的MCP服务器
1.项目结构简洁完整，支持docker compose部署
2.mcp client也提供一份代码
3.使用协程增强并发
4.提供1个接口
   - 根据名称 or 分子式 or SMILES搜索化学式 (默认使用分子式)
   - 返回完整的分子式信息json
   - 添加错误返回
   - 化合物需要英文名称
5.添加容错选项(不使用pubchempy)
   - 直接使用url获取化合物的json信息
   - MCP接口提供这个选项，默认(false)