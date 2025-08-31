# 开发难点记录

## 01: CORS跨域问题

### 问题描述
在开发AI角色聊天应用时，前端（Next.js运行在localhost:3000）无法访问后端（Django运行在localhost:8000）的API接口，出现以下错误：

```
Access to fetch at 'http://localhost:8000/api/chat/send_message/' from origin 'http://localhost:3000' has been blocked by CORS policy: Response to preflight request doesn't pass access control check: No 'Access-Control-Allow-Origin' header is present on the requested resource.
```

### 错误分析
1. **根本原因**：Django后端没有配置CORS（跨域资源共享）策略
2. **具体表现**：
   - 浏览器阻止了跨域请求
   - OPTIONS预检请求失败
   - POST请求无法到达后端API

### 解决方案
#### 1. 安装django-cors-headers包
```bash
pip install django-cors-headers
```

#### 2. 更新Django设置文件 (`backend/ai_character_chat/settings.py`)

**添加到INSTALLED_APPS:**
```python
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'corsheaders',  # 添加这一行
    'rest_framework',
    'chat',
]
```

**添加到MIDDLEWARE开头:**
```python
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # 添加到开头
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
```

**配置CORS设置:**
```python
# CORS settings for development
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
```

#### 3. 更新requirements.txt
确保包含 `django-cors-headers==4.4.0` (实际安装版本可能不同)

### 验证方法
1. **使用curl测试OPTIONS请求:**
   ```bash
   curl -X OPTIONS http://localhost:8000/api/chat/send_message/ -H "Origin: http://localhost:3000" -v
   ```

2. **检查响应头:**
   ```
   access-control-allow-origin: *
   access-control-allow-headers: accept, authorization, content-type, user-agent, x-csrftoken, x-requested-with
   access-control-allow-methods: DELETE, GET, OPTIONS, PATCH, POST, PUT
   ```

3. **测试实际POST请求:**
   ```bash
   curl -X POST http://localhost:8000/api/chat/send_message/ -H "Origin: http://localhost:3000" -H "Content-Type: application/json" -d '{"message": "test", "character_id": "1"}'
   ```

### 关键学习点
1. **CORS中间件位置很重要**: 必须放在MIDDLEWARE列表的前面，在其他中间件之前处理
2. **包名注意**: `django-cors-headers` (带连字符) vs `corsheaders` (下划线)
3. **开发环境配置**: `CORS_ALLOW_ALL_ORIGINS = True` 适合开发，生产环境应指定具体域名
4. **预检请求**: 浏览器会先发送OPTIONS请求，必须正确处理

### 相关文件
- `backend/ai_character_chat/settings.py` - Django配置文件
- `backend/requirements.txt` - Python依赖包列表

### 提交信息
- **Commit Hash**: `cb15fc2`
- **分支**: `v0.0.2`
- **类型**: `fix`
- **范围**: CORS配置

### 预防措施
1. 在新项目中预先配置CORS
2. 使用环境变量管理不同环境的CORS设置
3. 定期检查CORS配置的安全性
4. 在开发环境中测试跨域功能

---
*记录时间: 2025-08-31*
*解决开发者: AI Assistant*