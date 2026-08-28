# Chat UI Redesign Specification — V2

> **V2 supersedes V1(已删除 tray 抽屉思路)。**
> 解决"对话空间太小"问题 —— 把现有 420–680px 右栏重做成 **完全可任意拖拽的浮动 SoulPanel**,
> 默认收起为右下角细块,展开拖到屏幕任意位置,中央对话区不受任何右侧列挤压。

---

## 0. 为何 V1 被否决

V1 提议"底部细条 tray / drawer"形态,被认为和"不打扰对话"的本意不完全一致,且在 1280px 屏上数学上会反向挤压中央。
V2 把 SoulPanel 整个从 flexbox 列里挪出来,变成 `position: fixed` 的浮动 window,默认收为右下角细块,
用户主动拖到任意位置。

---

## 1. 现状(供对照)

来自 `frontend/src/app/page.tsx`、`ChatInterface.tsx`、`ImmersiveChatWindow.tsx`、`SoulPanel.tsx`。

| 区块 | 现状 | 关键行 |
|---|---|---|
| 左侧导航栏 | `w-[300px]`，默认展开 | `page.tsx:152` |
| 右侧 SoulPanel 区 | 固定 420px 默认展开,拖拽手柄可调到 320–680 | `page.tsx:169/187/198` |
| `xl:block` MemoryPanel | 底部常驻条 | `ChatInterface.tsx:374–393` |
| Memory 浮动展开 | `lg:hidden` 抽屉版 SoulPanel | `ChatInterface.tsx:359–372` |
| 中央消息容器 | `max-w-[min(48rem,86vw)]` ≈ 768px 居中 | `ImmersiveChatWindow.tsx:290` |
| 框架 | React 19 + Tailwind v4 | `package.json` |

**问题**:右栏 420px + 共享 flexbox 行,把中央对话宽度压到 ≈ 200–500px,聊条挤成纵列。

---

## 2. 用户已确认的设计决策(V2)

| # | 决策 | 内容 |
|---|---|---|
| D1 | 左栏 300px | 默认展开,保留 |
| D2 | 右栏 420–680px | **整列删除**(从 flexbox 行里抽掉) |
| D3 | 中央消息区 | **继续保持 768px(48rem)居中**,不因浮动窗而变窄 |
| D4 | SoulPanel 形态 | **完全可任意拖拽的浮动 window** —— 像 Photoshop/Figma 浮工具面板,可拖到屏幕任意位置 |
| D5 | 默认状态 | **收起为 右下角 一行细块** (~ 56×32px) |
| D6 | 内容(展开后) | **仅 SoulPanel: 记忆树 + 上传/删除**。**不**含 Memory 摘要 / Research / 会话元信息 |
| D7 | 持久化(D2 修订) | **位置 `(x,y)` 全局共享 / isOpen 按角色独立**(见 §6) |
| D8 | 移动端 | **< md 768 禁用任意拖拽 → 退化为右下 FAB + 底部 sheet 全屏覆盖**(见 §7) |
| D9 | 浮动方式 | **手写 Pointer Events 的 useDraggable hook(~50 行),不引 react-draggable**(见 §5) |

---

## 3. 设计目标

- **G1** 没主动展开时:中央对话区宽度 = 父容器宽度(仅 300px 左栏占用),细块右下角贴边不干扰对话。
- **G2** 展开浮动窗时:中央对话 768px 居中**保持不变**(浮动窗 `position: fixed` 不挤压)。
- **G3** 用户可把浮动窗拖到任意位置;位置 localStorage 持久化,刷新后回到原位置。
- **G4** 拖拽不跳出 viewport,有边界 clamp 保护;双击拖手柄可复位。
- **G5** 与现有调色板(slate / sky / emerald / amber)对齐,不出现 ghost 元素。
- **G6** A11y:`role="region"` 而 **非** `dialog`(避免焦点陷阱),Ctrl/Cmd+M 快捷键,Esc 收起,焦点不锁。

---

## 4. 新组件 —— `FloatingSoulPanel`(新文件)

### 4.1 文件位置
`frontend/src/components/FloatingSoulPanel.tsx`
并由 `frontend/src/app/page.tsx` 在外层 `<div className="flex h-screen w-full">` 里挂载(作为 `aside` 与 `main` 的兄弟)。

### 4.2 Props 接口

```ts
interface FloatingSoulPanelProps {
  characterId: string | null;     // null = 没选角色, 隐藏整个浮动块
  refreshKey?: string;            // 传给内部 SoulPanel, 触发重新拉数据
  defaultDocked?: 'bottom-right' | 'bottom-left' | 'top-right' | 'top-left'; // 默认 'bottom-right'
}
```

### 4.3 形态 / 状态机

| 状态 | 尺寸 | 内容 | 阴影 | 拖拽规则 |
|---|---|---|---|---|
| **Collapsed** | 56×32px 单行细 pill | `[📁 Memory] ▾` chip + chevron | `shadow-[0_8px_28px_rgba(15,23,42,0.08)]` | **整块** 任意点击触发拖动 (`cursor-grab`) |
| **Expanded** | 520×min(80vh, 640)px 浮动窗 | header bar (`cursor-grab` ★拖手柄) + 关闭 + `<SoulPanel isOpen />` | `shadow-[0_24px_80px_rgba(15,23,42,0.18)]` | **只有顶部 header bar** 是拖手柄;内容区点击**不**触发拖 |
| **Mobile (< md)** | 全宽顶部条 (collapsed) / 全屏 (expanded) | 同上,但背景 sheet overlay | 不同 | **完全禁用拖拽**;位置 fixed 全局定位 |

> ★ **关键 UX**: 收起态整块可拖 → 浮窗感强;展开态只有 header 一条可拖 → 不会在跟"记忆树"互动时误飞。
> 这两态拖手柄行为不同,在 spec §6 用 useDraggable hook 区分处理。

### 4.4 头部 header bar 形态(展开态)

```
┌──────────────────────────────────────────────────┐ ← cursor-grab ★
│ 📁  Memories                       ─    ×        │
└──────────────────────────────────────────────────┘
               (此处以下都是 SoulPanel 内容)
```

`★` 区域高 44px,内含:标题(`Memory`)、收缩控件(Minimize → 回到 Collapsed)、关闭按钮(×)。
—— 不要的:不搞 Settings / Pin / 等次级按钮,极简 4 个视觉元素 head。

### 4.5 视觉 token

跟现有调色板对齐:
- 收起 chip:`bg-white/90 backdrop-blur`, `ring-1 ring-slate-200/60`, `text-slate-700`
- 展开窗:`bg-white/95 backdrop-blur-xl`, `rounded-2xl`, `border border-slate-200/80`
- 标题文字:`text-sm font-semibold text-slate-900`

---

## 5. `useDraggable` hook(新文件)

### 5.1 文件位置
`frontend/src/hooks/useDraggable.ts`(新建)

### 5.2 接口

```ts
interface UseDraggableOptions {
  initialPosition: { x: number; y: number };
  storageKey?: string;             // localStorage key, 持久化
  onPositionChange?: (pos: {x,y}) => void;
  disabled?: boolean;              // mobile / 显式 disable
  boundary?: { margin?: number };  // 默认 margin=16
}

function useDraggable(opts: UseDraggableOptions): {
  position: { x: number; y: number };
  dragHandleProps: {
    onPointerDown: (e: React.PointerEvent) => void;
    onPointerMove: (e: React.PointerEvent) => void;
    onPointerUp: (e: React.PointerEvent) => void;
    onDoubleClick: () => void;     // 复位 = 回到 defaultDocked
    style?: React.CSSProperties;   // 提供 transform will-change
  };
  reset: () => void;
}
```

### 5.3 实现要点(伪代码思路,非完整)

```ts
// 用 native pointer events + setPointerCapture
const startDrag = (e) => {
  e.currentTarget.setPointerCapture(e.pointerId);
  setDragState({ startX: e.clientX, startY: e.clientY, originX, originY });
};

const onMove = (e) => {
  if (!dragState) return;
  const nextX = dragState.originX + (e.clientX - dragState.startX);
  const nextY = dragState.originY + (e.clientY - dragState.startY);
  setPosition({ x: nextX, y: nextY }); //  用 transform: translate3d 替代 top/left
};

const onUp = () => { clampPosition(); persist(localStorage); };

const clampPosition = () => {
  // clamp(16, x, window.innerWidth - panelWidth - 16)
  // clamp(16, y, window.innerHeight - panelHeight - 16)
};

const onResize = () => clampPosition(); // window resize 时也校准
```

### 5.4 性能细节

- 用 `transform: translate3d(x,y,0)` 而非 `top/left`(GPU 合成层)
- 不在 onPointerMove 里 setState 走 React;ref + 直接操作 element.style.transform,在 onPointerUp 时再 setState 持久化
- `will-change: transform` 仅在 dragging 期间加上,松开后移除
- `passive: true`(虽然 pointer events 没这选项,但 onMove 里别 preventDefault)

### 5.5 双击复位

`onDoubleClick` → `reset()` → 把 position 设回 `defaultDocked` 计算的初始位置 + 写回 localStorage。

---

## 6. localStorage 持久化(D7 落实)

| Key | 类型 | 作用域 |
|---|---|---|
| `soul-panel:position` | `{x: number, y: number}` | **跨角色共享** —— 拖到满意位置就稳 |
| `soul-panel:isOpen` | `Record<characterId, boolean>` | **按角色独立** —— 用户在角色 A 喜欢开,在角色 B 喜欢关 |

读取时机:组件 mount 时读;写入时机:onPointerUp 完成时 + isOpen toggle 时。

**Fallback 兜底**(存档读不到 / Private Mode / Storage 满):
- 改为内存变量 + 默认停靠点(`bottom: 24, right: 24`)
- 写兜底 try/catch:抛异常就 console.warn,不抛出

---

## 7. 移动端 (D8) 设计

`window.innerWidth < 768`:

- `useDraggable` 立即 `return` 不绑定指针(节省触摸事件冲突)
- 收起态:CSS `position: fixed; left:0; right:0; bottom:0`,**贴底 full-width pill**,
  内含 `[📁 Memory]  ▾` 居中,高度 ~44px
- 展开态:CSS `fixed inset-0`,背景 `bg-slate-950/35 backdrop-blur-sm`,
  内含 `<SoulPanel isMobile />` + × 关闭按钮右上角
- 不读 / 不写 localStorage(避免移动端横竖屏旋转引发意外 width)

**A11y 移动端仍生效**:`role="region"` + `aria-expanded`。

---

## 8. A11y(G6 落实)

| 项目 | 实现 |
|---|---|
| Wrapper 角色 | **`role="region"`** + `aria-label={copy.floatingSoulPanel.regionLabel}` —— **不要用 `dialog`**(避免焦点陷阱) |
| 拖手柄 | `aria-label="Drag to move"`, `tabIndex=0`(键盘可达) |
| 收起/展开按钮 | `aria-expanded={isOpen}` + `aria-controls="soul-panel-content"` |
| Esc 收起 | 全局 `window keydown` 仅在 `isOpen` 为 true 时 close |
| Ctrl/Cmd+M 快捷键 | `key === 'm' && (metaKey || ctrlKey)` → toggle panel |
| 焦点不被锁 | 焦点可自由进出浮动窗(区域模式);内部 `SoulPanel` 自带 a11y 不变 |
| prefers-reduced-motion | 如果用户偏好降低动效,收起→展开直接 snap(去除 transition) |

**保留原 `SoulPanel` 的 a11y 不动**(它有 aria、键盘焦点、自带按钮 label)。

---

## 9. 改动文件汇总

### 新增
- `frontend/src/components/FloatingSoulPanel.tsx`
- `frontend/src/hooks/useDraggable.ts`

### 修改
- `frontend/src/app/page.tsx`
  - 删除:`isRightPanelOpen` / `rightPanelWidth` / `isResizingRightPanel` state
  - 删除:resize useEffect + WorkspaceRightPanel 函数体
  - 删除:header 的 `PanelRightOpen` 按钮
  - 删除:右侧整个 div + 内部 SoulPanel 挂载点
  - 删除:`onSoulRefreshKeyChange` prop 传值(soulRefreshKey 挪到 ChatInterface 内部)
  - 删除:`soulRefreshKey` state
  - **新增**:在最外层 div 末尾挂载 `<FloatingSoulPanel characterId={selectedCharacterId} refreshKey={...} />`
  - import 清理:`PanelRightOpen` / `FolderTree` / `ChevronRight` / `WorkspaceRightPanel` 函数
- `frontend/src/components/ChatInterface.tsx`
  - 删除:`showSoulPanel` state
  - 删除:lg:hidden 的 SoulPanel 圆形按钮
  - 删除:`showSoulPanel && character && (...lg:hidden 抽屉 ...)`
  - 删除:`xl:block` 的底部 `MemoryPanel` 整块
  - 删 import:`FolderTree` / `SoulPanel` / `MemoryPanel`
- `frontend/src/i18n/messages.ts`(如必要,新增 `floatingSoulPanel` 区段,见 §10)

### 不动
- `frontend/src/components/SoulPanel.tsx`(直接复用)
- `frontend/src/components/ImmersiveChatWindow.tsx`(不动)
- `frontend/src/components/CharacterGallery.tsx`(不动)
- `frontend/src/components/ResearchPanel.tsx`(不动)
- `frontend/src/components/MemoryPanel.tsx`(代码保留,不引用)
- `frontend/package.json`(不引入 `react-draggable`)

---

## 10. i18n 新增 key(可选,但要做)

```ts
// en-US
floatingSoulPanel: {
  collapsedLabel: 'Memory',
  regionLabel: 'Memory panel',
  dragHandleLabel: 'Drag to move',
  closeLabel: 'Close memory panel',
}

// zh-CN
floatingSoulPanel: {
  collapsedLabel: '记忆',
  regionLabel: '记忆面板',
  dragHandleLabel: '拖动以移动',
  closeLabel: '关闭记忆面板',
}
```

加在 `frontend/src/i18n/{en-US.ts,zh-CN.ts}` 与 i18n 入口索引相应位置。

---

## 11. 验收标准

| ID | 标准 | 验证 |
|---|---|---|
| A1 | 进入 chat 页(已选角色),**默认** 浮动块收在右下角细块,不挡中央对话 | 截图 |
| A2 | 中央对话宽度保持 48rem 768px 居中(不因浮动窗而变) | DevTools / 截图 |
| A3 | 点浮动细块 → 160ms ease → 展开为 520×640px 浮动窗 | 视频 |
| A4 | 收起态整块可拖;展开态只有 header bar 可拖、内部内容不可拖 | 手动 |
| A5 | 拖到 viewport 边缘 → clamp 到 16px 边距,不出屏幕 | 手动 + 把窗口缩到 100px 宽 |
| A6 | 双击 header bar → 位置回 defaultDocked | 手动 |
| A7 | 拖完 + 刷新 → 浮动窗回到拖到的位置(isOpen 按 characterId 各角色记忆) | 手动 |
| A8 | Esc 收起;Ctrl/Cmd+M toggle;role="region" 可被读屏软件识别(不是 dialog) | a11y 工具 + 键盘 |
| A9 | 把窗口 resize 到 600px → 浮动窗自动 clamp 不死屏;窗口缩回 1280 → 还回到原位置 | 手动 |
| A10 | mobile < 768 → 浮动窗贴底全宽 / 展开为全屏 sheet;**不**响应拖拽 | DevTools mobile |
| A11 | 不依赖新 npm 包(`react-draggable` **不**安装) | `package.json` diff |
| A12 | 不残留 `isRightPanelOpen` / `WorkspaceRightPanel` 等旧代码 | grep |
| A13 | `pnpm exec tsc --noEmit` + `pnpm exec next lint` 全过 | 命令行 |

---

## 12. 关键 Review Point(实施者开工前要契定)

1. **R1** 拖完落点判断:onPointerUp 是写一次还是 debounced?
2. **R2** 双击复位能否在拖手柄上做(怕跟单拖冲突)?如果冲突,改用 header 旁边 small "↺" 图标。
3. **R3** 浮动窗长按右击是否暴露 context menu 复位 / 透明调节?Phase 2 可选,Phase 1 不做。
4. **R4** mobile 展开态 sheet 的关闭手势:除了 × 按钮,拖下界手势 1/3 高度否?Phase 2。
5. **R5** 多 floating panel 共存(未来加 Research / MemoryPanel 同样是浮动窗)的 z-index 调度:目前用 `z-40`,预留 `z-41/42/43/44` 给后续。

---

## 13. 风险 / 兜底

| 风险 | 兜底 |
|---|---|
| localStorage 满 / Safari Private Mode | 见 §6 Fallback;try/catch + 内存 mode |
| 拖到屏幕外侧死屏 | §5.3 clampPosition + resize 监听 |
| 浮动窗挡住 header 菜单 | 默认 bottom-right(避开 header),用户可拖开 |
| 浮动窗挡住 attachment preview z-50 | z-40 < z-50,preview 永远在上 |
| 浮动窗挡住 attachment 浮窗/ResPanel 横拉 | shared `z-30/40` 体系 + 各自 hide-on-blur(后续) |
| 移动端 touch event 与 drag 冲突 | §7 直接禁用拖 |

---

## 14. 实施步骤

1. **Step A**:写 `useDraggable` hook(独立可测),实现 §5 全部要点。
   - 单元自测:clamp / persist / 双击复位。
2. **Step B**:写 `FloatingSoulPanel.tsx`,接入 hook + i18n key + 现有 `SoulPanel`。
   - 自测:`characterId=null` 时不渲染 / `isOpen` toggle / Esc / 双击重置。
3. **Step C**:改 `page.tsx`,删右栏 + 删 state + 挂 FloatingSoulPanel。
4. **Step D**:改 `ChatInterface.tsx`,删 lg/hidden 抽屉 + xl:block 内存条 + state。
5. **Step E**:跑 `pnpm exec tsc --noEmit` + `pnpm exec next lint`。
6. **Step F**:`browser-use` + 手测:进 chat → 看右下角细块 → 拖 → 点开 → 体验 SoulPanel → 关 → 切角色 → Esc → 缩窗口 → Ctrl+M。
7. **Step G**(可选):出 ASCII wireframes 给 design board 看(我下一步可出)。

---

## 15. 与 V1 的差异汇总(shift)

| 维度 | V1 (已废弃) | V2 |
|---|---|---|
| 形态 | 底部细条 tray,从下往上展开 | 全屏任意拖浮动 window |
| 触发位置 | 固定 bottom 居中 | 默认 bottom-right,可拖任意 |
| 移动端 | "实施时再敲定" 占位 | 明确 sheet + FAB |
| 持久化 | 默认不记 | 位置全局 + isOpen 按角色 |
| a11y | tabIndex + role=button | role=region (避免 focus trap) + Ctrl+M |
| 包依赖 | 无(不精准) | 手写 hook,无新依赖 |

(本规范记录设计意图与改动面;**未**写实现代码。)
