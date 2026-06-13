# 视频上传 + 音频提取 设计说明

## 背景与目标

当前系统仅支持音频文件上传（`POST /{meeting_id}/upload`）。用户希望上传视频会议录制文件，自动提取音频后走现有 5-Agent Pipeline 处理。

**目标：** 新增独立视频上传接口，支持主流格式，FFmpeg 提取音频，流式处理大文件。

**成功标准：**
- 上传 .mp4/.mkv/.webm/.avi/.mov/.flv/.wmv 视频 → 自动提取音频 → 全流程零错误
- 支持 2GB 以内视频文件
- 格式不支持 / FFmpeg 缺失 / 无音频流 → 给出明确错误提示

## 现状与约束

- 已有 `POST /api/v1/meeting/{meeting_id}/upload` 仅处理音频
- `TranscriptionAgent._transcribe()` 接收 `bytes` → WhisperX
- 现有 `run_meeting_pipeline(audio_data=bytes)` 入口不变
- Python 依赖：已有 `httpx`、`loguru`、`tenacity`、`python-multipart`
- 系统约束：FFmpeg 需单独安装（不随 pip 安装）

## 方案对比

### 方案一：FFmpeg 命令行（推荐）

通过 `asyncio.create_subprocess_exec` 调系统 ffmpeg，从视频提取音频输出到 stdout pipe。

- 优点：格式支持最全、速度最快、无额外 Python 依赖、内存友好（pipe 模式）
- 缺点：服务器必须预装 FFmpeg

### 方案二：moviepy

- 优点：纯 Python API，自带 FFmpeg 二进制
- 缺点：依赖重（~50MB 额外包）、大文件内存占用高、社区维护不稳定

### 方案三：复用现有上传接口

扩展原有 `/upload` 端点，自动检测文件类型分发。

- 优点：少一个接口
- 缺点：职责混乱，一个接口做两件事，后期不好维护

## 推荐方案

**方案一（FFmpeg 命令行）+ 独立接口（方案三不采用）**。

理由：FFmpeg 是业界标准，格式覆盖最全，pipe 模式避免磁盘 IO 双倍写入。独立接口职责单一，便于后期扩展（如视频转码、截图预览等）。

## 详细设计

### 架构

```
客户端上传视频 (.mp4/.mkv/.webm/.avi/.mov/.flv/.wmv)
       │
       ▼
POST /api/v1/meeting/{meeting_id}/upload-video
       │
       ▼
1. 校验格式 → 不支持的格式返回 400
2. 流式写临时文件 (.upload_{uuid}.mp4) 到系统 temp 目录
3. asyncio.create_subprocess_exec("ffmpeg", "-i", path, "-vn",
   "-ar", "16000", "-ac", "1", "-f", "wav", "pipe:1")
4. 捕获 stdout → bytes (16kHz mono WAV)
5. finally 删除临时文件
6. run_meeting_pipeline(audio_data=audio_bytes)
       │
       ▼
   现有 5-Agent Pipeline（不变）
```

### 关键组件

**新增 `python/src/utils/media_utils.py`：**

```python
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".flv", ".wmv"}

def is_video_file(filename: str) -> bool:
    """通过扩展名判断是否为支持的视频格式"""

async def save_upload_streaming(upload_file: UploadFile, dest_path: Path) -> int:
    """分块写入磁盘，返回写入字节数，避免大文件撑爆内存"""

async def extract_audio_from_video(video_path: Path) -> bytes:
    """调 FFmpeg 从视频提取音频，返回 16kHz mono WAV bytes"""
```

**修改 `python/src/websocket/server.py`：**

新增端点：
```python
@app.post("/api/v1/meeting/{meeting_id}/upload-video")
async def upload_video(meeting_id: str, file: UploadFile = File(...)):
```

### 数据流

```
UploadFile → save_upload_streaming → temp .mp4 file
                                        │
                              ffmpeg subprocess (stdout pipe)
                                        │
                              audio_bytes (WAV, 16kHz mono)
                                        │
                              run_meeting_pipeline(audio_data=audio_bytes)
                                        │
                              返回同 /upload 的结构
```

### 异常与边界处理

| 场景 | HTTP 状态码 | 错误信息 |
|---|---|---|
| 不支持的格式 | 400 | "不支持的视频格式: .xxx，支持: .mp4, .mkv, .webm, .avi, .mov, .flv, .wmv" |
| FFmpeg 未安装/执行失败 | 500 | "音频提取失败: FFmpeg 不可用" |
| 视频损坏/无音频流 | 422 | "无法从视频中提取音频流" |
| 空文件 | 400 | "上传文件为空" |
| 临时文件残留（崩溃时） | — | finally 块确保清理，启动时可清理遗留 temp 文件 |

### 测试策略

- **单元测试** `tests/test_media_utils.py`：`is_video_file()` 各种扩展名
- **单元测试** `test_extract_audio()`：用 ffmpeg 生成 5 秒测试视频 → 提取 → 验证返回非空 WAV bytes
- **集成测试** `test_upload_video_endpoint`：上传测试视频 → 验证 pipeline 完整结果
- **边界测试**：无音频流的视频、损坏的视频、不支持的格式

## 风险与待确认项

- **FFmpeg 版本**：需确认生产环境 FFmpeg 版本 ≥ 4.0（建议 5.0+）
- **临时目录空间**：2GB 视频 + 提取内存需要约 3GB 可用空间
- **并发限制**：大视频并发上传可能导致磁盘 IO 瓶颈，后期可加请求队列
