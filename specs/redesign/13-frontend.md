# 13 · 前端

## 决策:Vite + React + React Router(Declarative mode)+ TanStack Query + openapi 类型闭环 + Base UI + react-i18next

前端**完全重写**为 Vite SPA(删 Next.js)。RESTful `/reports/:id` 运行时动态路由 + 静态客户端应用是硬约束,Vite 是唯一原生满足二者的方案。

## 框架决策:Vite + React(删 Next.js)

### 决策理由(源码核实)

- **应用是纯客户端**(全 `"use client"`,无 SSR/SEO 需求)。Next 的 standalone Node server + RSC/App Router 对纯 admin dashboard 是 overkill。
- **RESTful 运行时动态路由是硬约束**:Next `output: "export"` **不支持**运行时动态路由 `/reports/123`(源码核实 `nextjs/docs/01-app/02-guides/static-exports.mdx:280-281`:dynamic routes without generateStaticParams 不支持;报告 id 运行时生成,无法 build 时枚举)。
- **Next 官方立场**:Next "从 Vite 迁移"文档把"纯客户端 SPA"定位为 Vite 的劣势,把 Next 定位为升级方案——即 Next 官方认为纯 SPA 是 Vite 的领域。
- **Vite 单 `index.html` + 客户端路由 + Caddy `try_files /index.html` 回退**:正是标准 SPA 静态托管模式,React Router 用户熟悉。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| Next + `output: "export"` | 不支持运行时动态路由 `/reports/:id`(RESTful 硬约束) |
| Next + Node server(standalone) | 3 进程架构 + 双重回环(Caddy→Node→Caddy→FastAPI)+ Node-FastAPI 服务端耦合;性能优势(SSR 首屏)对内网 admin 用不上;违背"静态客户端应用"诉求 |
| Next + export + 查询参数 `/report?id=` | 放弃 RESTful(硬约束) |

## 路由:React Router(Declarative mode,v7/v8)

### 选型理由(源码核实)

- **Vite 官方不 endorse 任何 router**(create-vite React 模板零 router;Vite 只 endorse `@vitejs/plugin-react`)。React Router 与 TanStack Router 在 Vite 生态是**平级 peer**。
- **React Router 是惯例、迁移成本最低**:项目已有 `react-router-dom@6`,v6→v7 设计为**非破坏性**(future flags)。
- **官方 Vite + BrowserRouter 配方存在**:`react-router/docs/start/declarative/installation.md` 明示。
- **静态 SPA 托管**:`react-router/docs/how-to/spa.md` 确认 `/* /index.html 200` 标准 SPA 托管。
- **"library mode" 是过时术语**,现叫 **Declarative mode**(`react-router/docs/start/modes.md`)。

### 命名修正(记录)

- "React Router v7 library mode" → **"React Router(Declarative mode),目标 v7 或 v8"**。
- 理由从"官方推荐组合"改为"**惯例、迁移成本最低**"。
- 当前 React Router 是 v8.2.0(v7 是上一代);v8 移除 `react-router-dom`(改从 `react-router/dom` 导入)。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| TanStack Router | 类型安全更强,但非 Vite 官方推荐;迁移成本高(重写所有路由) |
| React Router Framework mode | 引入 SSR 机制(我们不需要) |

## 资源命名:`reports`(复数)

- REST 惯例 + 与 API `/api/v1/reports` + 表名 `reports` 一致。
- 前端路由:`/reports`(列表)+ `/reports/:id`(详情)。

## API 契约闭环(修 5 处契约断裂)

```
FastAPI response_model(Pydantic)→ /openapi.json → scripts/export_openapi.py 导出 web/openapi.json
                                                                  ↓
                          openapi-typescript web/openapi.json -o src/api/schema.ts
                                                                  ↓
                          openapi-fetch createClient<paths>() + openapi-react-query $api.useQuery
```

- **前端类型永不手写**,CI drift 检查(12 已定 openapi 静态导出)。
- 修当前 5 处契约断裂(`/config/validate-data` 不存在、`ConfigSaveRequest` 缺 version、`useConfigSchema` 类型不匹配、`useConfig` 类型不匹配、`validateConfig` 请求体不匹配)。

## 技术栈(完整)

| 关注点 | 选型 |
|---|---|
| 构建 | Vite + `@vitejs/plugin-react` |
| 框架 | React 19 |
| 路由 | React Router(Declarative mode,v7/v8) |
| 数据获取 | TanStack Query |
| API 类型 | openapi-typescript + openapi-fetch + openapi-react-query |
| 组件原语 | **@base-ui/react**(硬性条件,MUI Base UI,前 Radix 团队下一代) |
| 样式 | Tailwind CSS v4(CSS-first)+ CVA |
| 表单 | React Hook Form + Zod |
| i18n | react-i18next(Vite 无 Next 绑定) |
| Markdown | react-markdown + remark-gfm + rehype-sanitize |
| 测试 | Vitest + Testing Library + msw + Playwright |
| Lint/Format | ESLint 9 flat + typescript-eslint + Prettier + prettier-plugin-tailwindcss |

## `@base-ui/react`(硬性条件)

- 保留 `@base-ui/react`(用户硬性要求)。
- 用 shadcn 的 `base` registry 变体或自建组件库。
- a11y 由 Base UI 保证(dialog 焦点陷阱、dropdown 键盘导航等)。

## Markdown 安全(修存储型 XSS)

- 客户端 `react-markdown` + `remark-gfm` + `rehype-sanitize`(allowlist)。
- defense-in-depth(后端 09 也 nh3)。
- 删 `dangerouslySetInnerHTML` 裸用。

## i18n(修"i18n 摆设")

- **react-i18next**(Vite 无 Next 绑定,从 next-intl 换)。
- 修"i18n 摆设":当前仅 15 个 `nav.*` 键翻译,页面几十个可见串硬编码英文 → 所有用户可见串进 JSON catalog。
- `<html lang>` 随 locale 切换更新。
- locale code 统一小写(呼应 11)。

## 样式统一(修双系统漂移)

- Tailwind v4 统一。
- 删手写 `index.css` ~500 行 `@layer components` 死代码(与 Tailwind/CVA 重复)。
- 删无效 `prose-gray`/`prose-invert`(typography 插件未装);若需 prose 样式手写或装 `@tailwindcss/typography`。

## 工程基础

- **ESLint 9 flat config**(修当前 `eslint .` 但 ESLint 未装的坏脚本)+ `typescript-eslint`。
- **Prettier** + `prettier-plugin-tailwindcss`。
- **tsconfig**:`strict` + `noUncheckedIndexedAccess`(openapi-fetch 要求)+ `moduleResolution: "bundler"`。
- **404 页 + lazy loading**。
- **测试**:Vitest + RTL + msw(已有,补测试)+ Playwright e2e。

## Vite 配置

- 标准 Vite + React 工程(删 `next.config.ts`/`next-intl`/`output: export`/`rewrites()`)。
- `web/` 改为标准 Vite 工程。
- 构建:`pnpm build` → `dist/`(Vite 默认输出)。
- ⑭ Docker:Caddy serve `dist/` + `try_files {path} /index.html`(单回退规则覆盖所有路由)。

## 删除清单

| 删除 | 理由 |
|---|---|
| `web/`(Next.js 16) | 改 Vite 重写 |
| `src/progress/web/`(旧 Vite+React18+SWR 副本) | 顶层 `web/` 统一 |
| 手写 API 类型(`lib/api/reports.ts` 等) | openapi 生成 |
| `dangerouslySetInnerHTML` 裸用 | rehype-sanitize |
| next-intl | react-i18next |
| 坏的 lint 脚本(ESLint 未装) | 装 ESLint 9 flat |
| 双样式系统 | Tailwind v4 统一 |
