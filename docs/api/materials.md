# Materials API

## 职责

资料是学习内容的 canonical 入口：上传/创建、列表、检索、详情、删除，以及章节选择。资料删除和更新会联动派生检索/知识投影生命周期。

## Stable 前端能力

| 业务函数 | HTTP Contract | 用途 |
| --- | --- | --- |
| `listMaterials()` | `GET /api/materials/` | 资料列表；service 自动按后端 100 条上限分页 |
| `searchMaterials()` | `GET /api/materials/search` | 语义/关键词路由检索，可按 Project 过滤 |
| `uploadMaterial()` | `POST /api/materials/upload` | multipart 上传，返回解析后的 `MaterialUploadResult`，不是原生 `Response` |
| `getMaterial()` | `GET /api/materials/{material_id}` | 获取正文和状态 |
| `deleteMaterial()` | `DELETE /api/materials/{material_id}` | 删除 canonical 资料 |
| `listMaterialChapters()` | `GET /api/materials/{material_id}/chapters` | Goal Plan 的章节选择 Contract |

前端 Service：`frontend/src/services/materialApi.ts`。

## 关键响应

`MaterialItem` 至少包含：`id`、`title`、`created_at`、`updated_at`；可携带 `file_type`、`content`、`project_ids`、`retrieval_projection`、`knowledge_extraction`。

章节接口返回稳定的轻量结构：`id`、`title`、`parent_id`、`order_index`、`mastery_level`。它通过资料 ownership 做用户隔离。

## 上传约束

当前允许 PDF / DOCX / TXT / Markdown；后端校验扩展名、content-type、文件签名和大小，并使用服务端生成文件名。重复文件可能返回 `duplicate=true` 并复用已有资料。
