# MyTube — YouTube 视频流系统

基于《System Design Interview》第 14 章（Youtube 设计）实现的完整视频上传→转码→流媒体播放系统。

## 功能特性

- **并行上传流程**：元数据与视频二进制分离处理，二进制经预签名 URL 直传存储
- **真实 ffmpeg 转码**：按源分辨率自适应产出 1080p / 720p / 480p 三档 HLS
- **HLS 自适应码率播放**：master.m3u8 + GOP 对齐分片，浏览器可切换画质
- **消息队列解耦**：Redis List 队列，上传与转码流水线完全解耦
- **事件驱动状态回写**：Worker 只发事件不写库，api-server 单写者更新 SQLite
- **错误分类与重试**：可恢复错误（退避重试 2/4/8s）与不可恢复错误（直接 failed）区分；failed 视频支持一键重试
- **Worker 心跳与水平扩展**：`worker:{instance_id}` 心跳键 + `/api/stats` 实时统计，`docker compose up --scale transcoder-worker=N` 即可扩容
- **完整前端**：Vue 3 暗色主题，视频网格 / 拖拽上传（进度条）/ HLS 播放器（画质切换）

## 架构

```
                    ┌─────────────┐
  浏览器 ──上传元数据──▶  api-server │──insert──▶ SQLite (videos/renditions)
  浏览器 ──二进制流───▶  (FastAPI)  │◀──消费─── transcode:events
                    └──────┬──────┘
                           │ push task
                           ▼
                   ┌──────────────┐         ┌─────────────────┐
                   │ Redis 队列    │──BLPOP──▶ transcoder-worker │──▶ ffmpeg
                   │ transcode:tasks│        │ (Preprocessor/  │    多档并行编码
                   └──────────────┘         │  Resource Mgr/  │
                                            │  Task Workers)  │
                                            └───────┬─────────┘
                                                    │ 写 HLS 分片
                                                    ▼
  浏览器 ◀──/media/*.m3u8,*.ts──┌─────┐    ./data/transcoded/{video_id}/
                                │ CDN │        ├── master.m3u8
                                └─────┘        ├── 1080p/playlist.m3u8 + seg_*.ts
                                               ├── 720p/ ...
                                               ├── 480p/ ...
                                               └── thumbnail.jpg
```

转码流水线（Worker 内部，对应设计文档 DAG Scheduler + Resource Manager + Task Workers）：

```
任务 ─▶ Preprocessor(ffprobe 校验/选档) ─▶ processing 事件
     ─▶ Resource Manager(Semaphore 并发) ┬▶ 1080p 编码 ┐
                                          ├▶ 720p  编码 ├▶ master.m3u8 ─▶ ready 事件
     thumbnail.jpg（失败非致命）───────────┘▶ 480p  编码 ┘
```

## 目录结构

```
youtube-system/
├── app/                     # api-server（单写者）
│   ├── config.py            # 配置（路径/队列/上传限制）
│   ├── models.py            # Pydantic 请求模型
│   ├── database.py          # aiosqlite 数据访问
│   ├── presign.py           # 预签名 token（单次使用/TTL 300s）
│   ├── queue.py             # Redis 队列助手
│   ├── completion_consumer.py  # 事件消费 → 状态回写
│   └── server.py            # FastAPI 7 端点
├── worker/                  # 转码 Worker（可多实例）
│   ├── config.py
│   ├── preprocessor.py      # ffprobe + 档位选择
│   ├── task_worker.py       # ffmpeg 编码/缩略图/master 播放列表
│   ├── resource_manager.py  # Semaphore 并发控制 + 排空
│   ├── pipeline.py          # 流水线编排 + 事件上报
│   └── main.py              # 心跳/消费循环/health
├── cdn/nginx.conf           # HLS MIME + CORS
├── frontend/                # Vue 3 + HLS.js
├── api.Dockerfile / worker.Dockerfile
└── docker-compose.yml
```

## 快速开始

```powershell
cd youtube-system
docker compose up -d --build
```

启动后访问：

| 服务 | 地址 |
|------|------|
| Web 前端 | http://localhost:8080 |
| api-server | http://localhost:8000/docs |
| CDN（媒体流） | http://localhost:8003 |

使用流程：打开 http://localhost:8080 → Upload → 拖入视频文件填写标题 → 上传后首页卡片显示 `pending → processing` → 转码完成后变 `ready`（约 10s 测试视频需 20~60s）→ 点击卡片观看，可切换画质。

水平扩容 Worker：

```powershell
docker compose up -d --scale transcoder-worker=3
```

## API

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/upload-url | 预签名上传（body: filename/size/content_type） |
| POST | /api/upload/{token} | 二进制流式上传（?filename= 推导扩展名） |
| POST | /api/videos | 注册元数据并入转码队列 |
| GET | /api/videos | 视频卡片列表 |
| GET | /api/videos/{id} | 详情（ready 含 stream_url 与 renditions） |
| POST | /api/videos/{id}/retry | 失败重试（仅 failed） |
| GET | /api/stats | Worker 数/排队任务数/各状态视频数 |

## 设计要点（对照设计文档）

1. **并行上传**：设计文档要求元数据与二进制走不同服务并行处理；本实现元数据在二进制落盘后注册（保证 `create_video` 校验二进制存在），时序上简化为顺序但接口边界保持分离。
2. **预签名 URL**：`presign.py` 模拟 S3 预签名——token 单次使用、TTL 300s、扩展名白名单、1GB 上限。
3. **转码 DAG**：Preprocessor 探测源并决定档位集合（≥1080p→3 档，≥720p→2 档），即设计文档中 DAG 的动态构建。
4. **Resource Manager**：每 Worker `asyncio.Semaphore(CONCURRENCY)` 限制并发编码，停机时 `drain()` 排空在途任务。
5. **错误分类**：坏文件（ffprobe 失败/无视频流）→ 不可恢复直接 failed；ffmpeg 瞬时失败 → 指数退避重试 3 次；worker 内部崩溃 → failed 事件兜底，视频可通过 retry 重入队。
6. **心跳机制**：Worker 每 15s 续期 `worker:{instance_id}`（TTL 60s）；`/api/stats` SCAN 该前缀统计在线实例。
7. **CDN 模拟**：nginx 只读挂载 `data/transcoded`，HLS 正确 MIME + CORS + 一年强缓存。

## 技术栈

FastAPI · aiosqlite · Redis (List 队列) · ffmpeg (HLS/x264/AAC) · nginx (CDN/反代) · Vue 3 · vue-router · axios · HLS.js · Docker Compose
