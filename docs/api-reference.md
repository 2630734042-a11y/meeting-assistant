# API 参考文档

## REST API

### 创建会议
```
POST /api/v1/meeting/start

Response:
{
  "meeting_id": "abc123",
  "websocket_url": "ws://localhost:8000/ws/meeting/abc123",
  "status": "created"
}
```

### 运行演示
```
POST /api/v1/meeting/{meeting_id}/demo

Response: 完整的会议处理结果（转写+摘要+待办+洞察+跟进）
```

### 上传音频
```
POST /api/v1/meeting/{meeting_id}/upload
Content-Type: multipart/form-data
Body: file=@meeting.wav
```

### 获取转写结果
```
GET /api/v1/meeting/{meeting_id}/transcript
```

### 获取会议纪要
```
GET /api/v1/meeting/{meeting_id}/summary
```

### 获取待办事项
```
GET /api/v1/meeting/{meeting_id}/actions
```

### 获取会议洞察
```
GET /api/v1/meeting/{meeting_id}/insights
```

### 获取完整报告
```
GET /api/v1/meeting/{meeting_id}/report
```

## WebSocket API

### 连接
```
ws://localhost:8000/ws/meeting/{meeting_id}
```

### 发送消息
```json
{"type": "start"}    // 开始录制
{"type": "stop"}     // 停止录制，触发处理
{"type": "demo"}     // 运行演示模式
{"type": "ping"}     // 心跳
```

### 接收消息
```json
{"type": "connected", "meeting_id": "..."}
{"type": "recording", "buffer_size": 1024}
{"type": "processing", "message": "处理中..."}
{"type": "transcript", "data": {...}}
{"type": "summary", "data": {...}}
{"type": "actions", "data": {...}}
{"type": "insights", "data": {...}}
{"type": "completed", "meeting_id": "..."}
```
