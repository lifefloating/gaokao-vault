# gaokao-vault

[![Build status](https://img.shields.io/github/actions/workflow/status/lifefloating/gaokao-vault/main.yml?branch=main)](https://github.com/lifefloating/gaokao-vault/actions)
[![License](https://img.shields.io/github/license/lifefloating/gaokao-vault)](https://github.com/lifefloating/gaokao-vault/blob/main/LICENSE)

阳光高考全量数据抓取系统 — 从 [gaokao.chsi.com.cn](https://gaokao.chsi.com.cn) 抓取 13 类高考数据，存入 PostgreSQL，支持全量/增量抓取、断点续爬、反爬对抗。

## 功能

- 13 类数据源：院校、专业、分数线、一分一段、招生计划、章程、满意度等
- 三阶段任务编排，自动处理数据依赖
- content_hash (SHA-256) 增量去重 + 变更追踪
- 双 Session 反爬：HTTP 快速请求 + Stealth 浏览器自动切换
- 三层代理池：付费代理 > 免费代理 > 直连
- 断点续爬（Ctrl+C 暂停，再次启动自动恢复）
- Typer CLI

## 技术栈

| 组件 | 技术 |
|------|------|
| 爬虫框架 | [Scrapling](https://github.com/D4Vinci/Scrapling) (Spider + FetcherSession + AsyncStealthySession) |
| 数据库 | PostgreSQL + [asyncpg](https://github.com/MagicStack/asyncpg) |
| CLI | [Typer](https://typer.tiangolo.com/) |
| 数据校验 | [Pydantic](https://docs.pydantic.dev/) + pydantic-settings |

## 数据类型

| 类型 | 说明 | 预估量 |
|------|------|--------|
| schools | 院校信息 | ~2,900 |
| majors | 专业知识库 | ~3,000 |
| school_majors | 院校-专业关联 | ~100,000 |
| score_lines | 历年批次线 | ~数万 |
| score_segments | 一分一段表 | ~百万 |
| enrollment_plans | 招生计划 | ~百万 |
| charters | 招生章程 | ~数万 |
| timelines | 志愿填报时间线 | ~数百 |
| special | 特殊类型招生 | ~数千 |
| school_satisfaction | 院校满意度 | ~数千 |
| major_satisfaction | 专业满意度 | ~数千 |
| interpretations | 专业解读 | ~数千 |
| announcements | 省级招办公告 | ~数千 |
