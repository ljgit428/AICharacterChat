# Docker Desktop Redis 启动指南

## 方法一：使用 Docker Desktop GUI (推荐)

### 步骤 1：重启 Docker Desktop
1. 完全关闭 Docker Desktop：
   - 右键点击系统托盘中的 Docker Desktop 图标
   - 选择 "Quit Docker Desktop"
   - 等待几秒钟

2. 重新启动 Docker Desktop：
   - 在开始菜单中搜索 "Docker Desktop"
   - 点击启动

### 步骤 2：使用 Docker Compose 启动 Redis
1. 打开命令提示符或 PowerShell
2. 导航到项目目录：
   ```
   cd d:\git\project\AICharacterChat
   ```
3. 运行以下命令启动 Redis：
   ```
   docker-compose up -d
   ```

### 步骤 3：验证 Redis 是否运行
1. 运行测试命令：
   ```
   docker ps
   ```
2. 应该能看到 redis 容器正在运行
3. 测试 Redis 连接：
   ```
   docker exec redis-server redis-cli ping
   ```
   应该返回 "PONG"

## 方法二：手动创建 Docker 容器

如果 Docker Compose 不工作，可以手动创建容器：

```
docker run -d -p 6379:6379 --name redis-server redis:latest
```

## 方法三：使用 Docker Desktop GUI 直接创建

1. 打开 Docker Desktop
2. 点击 "Containers" 标签
3. 点击 "Create" 或 "Run"
4. 输入以下配置：
   - Image: `redis:latest`
   - Port: `6379:6379`
   - Name: `redis-server`
5. 点击 "Run"

## 故障排除

### 如果 Docker Desktop 无法启动：
1. 重启电脑
2. 检查 Windows 更新
3. 以管理员身份运行 Docker Desktop

### 如果端口被占用：
1. 检查端口 6379 是否被占用：
   ```
   netstat -ano | findstr 6379
   ```
2. 如果被占用，停止占用端口的进程或使用不同的端口

### 如果容器启动失败：
1. 查看容器日志：
   ```
   docker logs redis-server
   ```
2. 删除并重新创建容器：
   ```
   docker stop redis-server
   docker rm redis-server
   docker run -d -p 6379:6379 --name redis-server redis:latest