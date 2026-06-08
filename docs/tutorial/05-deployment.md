# 教程 05 - 部署上线

> Docker化、CI/CD 基础、云部署指南

---

## 方案一: Docker 部署（推荐）

### 1. 使用 docker-compose

```bash
cd python

# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f meeting-assistant

# 停止
docker-compose down
```

这会启动：
- meeting-assistant: 主服务（8000端口）
- postgres: 数据库（5432端口）
- redis: 缓存（6379端口）

### 2. 自定义 Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y ffmpeg
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "src.websocket.server:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 方案二: 直接部署

```bash
# 安装依赖
pip install -r requirements.txt

# 生产模式启动
uvicorn src.websocket.server:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 方案三: Kubernetes

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: meeting-assistant
spec:
  replicas: 2
  selector:
    matchLabels:
      app: meeting-assistant
  template:
    metadata:
      labels:
        app: meeting-assistant
    spec:
      containers:
      - name: meeting-assistant
        image: meeting-assistant:latest
        ports:
        - containerPort: 8000
        envFrom:
        - secretRef:
            name: meeting-secrets
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2000m"
---
apiVersion: v1
kind: Service
metadata:
  name: meeting-assistant
spec:
  type: LoadBalancer
  ports:
  - port: 80
    targetPort: 8000
  selector:
    app: meeting-assistant
```

---

## 环境变量管理

**关键原则**: API Key 等敏感信息永远不要写在代码里。

```bash
# 开发环境: .env 文件
cp .env.example .env

# 生产环境: 系统环境变量 或 K8s Secret
kubectl create secret generic meeting-secrets \
  --from-literal=MINIMAX_API_KEY=xxx \
  --from-literal=JIRA_API_TOKEN=xxx
```

---

## 健康检查

```bash
# 服务健康检查
curl http://localhost:8000/

# 预期返回
{"name": "多Agent智能会议助手", "version": "1.0.0", ...}
```

---

## 恭喜完成！

你已经完成了从零到部署的全部教程。接下来可以：
1. 查看 [面试宝典](../interview/) 准备面试
2. 修改代码添加自己的功能
3. 部署到云服务器实际使用
