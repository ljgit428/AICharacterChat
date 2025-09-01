# 测试指南：解决 403 Forbidden 错误

## 问题概述

您的应用遇到了一个 `403 Forbidden` 错误，错误信息为 `{"detail":"Authentication credentials were not provided."}`。这是因为您的后端 API 需要用户登录才能访问，但前端没有发送任何身份验证信息。

## 解决方案

我们提供了两种解决方案：

### 方案一：快速解决（用于开发测试）

这种方法允许无身份验证访问，适用于快速开发和测试。

#### 后端修改

1. **修改权限设置**：所有 ViewSet 的 `permission_classes` 已设置为 `[]`（允许无身份验证访问）
2. **处理用户依赖**：所有依赖 `request.user` 的代码已修改为使用默认用户 `default_user`

#### 前端修改

无需修改前端代码，可以立即使用。

### 方案二：正确且安全的长期方案（推荐）

这种方法实现了完整的 Token 认证系统。

#### 后端修改

1. **配置 Token 认证**：
   - 在 `settings.py` 中添加 `rest_framework.authtoken` 到 `INSTALLED_APPS`
   - 配置 `REST_FRAMEWORK` 使用 `TokenAuthentication`

2. **创建认证端点**：
   - `/api/auth/login/` - 用户登录
   - `/api/auth/register/` - 用户注册
   - `/api/auth/logout/` - 用户登出

#### 前端修改

1. **修改 API 请求**：
   - 自动在请求头中包含 Token
   - 提供了 `setAuthToken`, `getAuthToken`, `removeAuthToken` 方法

2. **添加登录组件**：
   - 创建了 `LoginModal` 组件
   - 集成到主页面中

## 测试步骤

### 测试方案一（快速解决）

1. 启动后端服务：
   ```bash
   cd backend
   python manage.py runserver
   ```

2. 启动前端服务：
   ```bash
   cd frontend
   npm run dev
   ```

3. 打开浏览器访问 `http://localhost:3000`
4. 尝试发送消息，应该不再出现 403 错误

### 测试方案二（Token 认证）

1. 确保后端和前端服务已启动

2. 测试用户注册：
   - 点击 "Login" 按钮
   - 选择 "Register" 选项卡
   - 输入用户名和密码
   - 点击 "Register" 按钮

3. 测试用户登录：
   - 点击 "Login" 按钮
   - 输入用户名和密码
   - 点击 "Login" 按钮
   - 应该看到 "Welcome, [username]" 消息

4. 测试发送消息：
   - 发送消息应该正常工作
   - 所有 API 请求会自动包含 Token

5. 测试登出：
   - 点击 "Logout" 按钮
   - 应该返回到登录界面

## 切换方案

### 从方案一切换到方案二

1. 在 `backend/chat/views.py` 中将所有 `permission_classes = []` 改回 `permission_classes = [IsAuthenticated]`
2. 确保前端已实现 Token 认证（已完成）

### 从方案二切换到方案一

1. 在 `backend/chat/views.py` 中将所有 `permission_classes = [IsAuthenticated]` 改为 `permission_classes = []`
2. 确保所有依赖 `request.user` 的代码已处理（已完成）

## 注意事项

- **方案一** 仅适用于开发环境，不适用于生产环境
- **方案二** 是更安全、更完整的解决方案，推荐在生产环境中使用
- 在部署到生产环境之前，请确保：
  - 使用 HTTPS
  - 设置强密码
  - 实现密码重置功能
  - 添加 CSRF 保护
  - 实现会话管理

## 故障排除

### 如果仍然遇到 403 错误

1. 检查后端日志，确认权限设置正确
2. 检查前端是否正确发送了 Token
3. 确保后端 `rest_framework.authtoken` 已正确安装和配置

### 如果 Token 认证不工作

1. 检查前端是否正确存储了 Token
2. 检查请求头是否包含正确的 Authorization 格式：`Token <token>`
3. 确保后端 Token 认证后端已正确配置