## 根据smiles文本画图(2025-8-15)
1.根据API调用返回的smiles文本画出分子式的图片(可以使用库)
2.将图片转base64，然后上传到远程图片服务器(需要将返回的localhost地址替换为真实服务器地址)
  图片服务器调用示例:
  上传 base64 编码的图片
```shell
curl -X POST "http://localhost:8083/upload/base64" \
  -H "Content-Type: application/json" \
  -d '{
    "image_data": "iVBORw0KGgoAAAANSUhEUgAAAB...base64数据...",
    "filename": "test.png"
  }'
  # 示例响应
# {
#   "success": true,
#   "image_url": "http://localhost:8083/img/abcd1234...hash.jpg",
#   "hash": "abcd1234...hash",
#   "uploaded_at": 1755081301
# }

# 通过哈希值获取图片
curl "http://localhost:8083/img/abcd1234...hash.jpg" --output downloaded_image.jpg

```
3.图片远程链接和化学信息一起放进json返回
4.使用新端口8988