# File Upload & Artifact Image Reading Feature — Design Spec

**Date:** 2026-06-12  
**Status:** Approved  
**Owner:** opendev-py  

---

## Overview

This feature enables users to upload files and images through the web UI, store them in conversation- or project-scoped artifact folders, and provides the agent with tools to list and read artifacts dynamically during conversation.

**Key Goals:**
1. Allow users to upload files/images via web UI with 50MB max size, any format
2. Store files in conversation-scoped (`.artifacts/conversations/{id}/`) or project-scoped (`.artifacts/project/`) directories
3. Provide agent with `list_artifact_images()` and `read_artifact_image()` tools to access artifacts on-demand
4. Support full deletion (hard delete) of files from disk and database
5. Visually distinguish conversation vs. project artifacts in the UI

---

## Architecture & Storage

### File Organization

```
.artifacts/
├── conversations/
│   ├── {conversation_id}/
│   │   ├── {uuid_prefix}_image_001.png
│   │   ├── {uuid_prefix}_document.pdf
│   │   └── ...
└── project/
    ├── {uuid_prefix}_reference_image.jpg
    ├── {uuid_prefix}_design_spec.pdf
    └── ...
```

**Rationale:**
- UUID prefix on filenames prevents collisions if user uploads duplicate names
- Conversation files scoped by conversation_id
- Project files live in a shared project folder (accessible to all conversations in the project)

### Database Schema Extension

Extend the existing `Artifact` model with:
- `scope`: VARCHAR(20) — `"conversation"` or `"project"` (enables efficient queries)
- `local_path`: VARCHAR(512) — Relative path on disk (e.g., `conversations/123/image_abc123.png`)

Keep existing fields:
- `id`, `project_id`, `conversation_id`, `type`, `title`, `payload_ref`, `preview`, `pinned`, `created_at`, `updated_at`

### Storage Paths

- **Conversation artifacts:** `{conversation.working_directory}/.artifacts/conversations/{conversation_id}/{uuid_filename}`
- **Project artifacts:** `{project_root}/.artifacts/project/{uuid_filename}`
- Parent directories created automatically on first upload

### File Constraints

- **Max size:** 50MB per file
- **Supported formats:** Any (validation is permissive; agent gracefully handles unsupported types)
- **Naming:** Sanitized to remove dangerous characters; UUID prefix added to prevent collisions

---

## Agent Tools

### Tool 1: `list_artifact_images(scope)`

**Purpose:** Agent queries available images in artifact folders.

**Signature:**
```python
def list_artifact_images(scope: Literal['conversation', 'project', 'both']) -> list[dict]:
    """
    List artifact images by scope.
    
    Args:
        scope: 'conversation' (current conversation only), 
               'project' (project-level only), or 
               'both' (all conversation + project artifacts)
    
    Returns:
        [
            {
                'id': int,
                'filename': str,
                'type': str,  # 'image', 'pdf', 'code', etc.
                'size': int,  # bytes
                'scope': str,  # 'conversation' or 'project'
                'created_at': str  # ISO timestamp
            },
            ...
        ]
    """
```

**Implementation Details:**
- Filter by `is_deleted = false` and `scope` in query
- Order by `created_at DESC`
- Return empty list if no artifacts match scope

### Tool 2: `read_artifact_image(artifact_id)`

**Purpose:** Agent reads a specific artifact file.

**Signature:**
```python
def read_artifact_image(artifact_id: int) -> dict:
    """
    Read artifact file content.
    
    Args:
        artifact_id: ID from list_artifact_images()
    
    Returns (success):
        {
            'id': int,
            'filename': str,
            'type': str,
            'scope': str,
            'base64_content': str,  # Base64-encoded file content
            'content_type': str  # MIME type (e.g., 'image/png')
        }
    
    Returns (error, unsupported type):
        {
            'id': int,
            'filename': str,
            'error': 'Unsupported file type',
            'type': str
        }
    
    Returns (error, not found):
        {
            'error': 'Artifact not found or was deleted'
        }
    """
```

**Implementation Details:**
- Validate artifact_id exists and `is_deleted = false`
- Read file from disk using `local_path`
- For images (png, jpg, jpeg, gif, webp, svg): Return base64 content + MIME type
- For other files (pdf, txt, etc.): Return graceful error message
- If file missing from disk: Return `{error: 'File not found on disk'}`

---

## User Interface

### Upload Interface

**Location:** Message input area (near send button or in separate upload widget)

**Components:**
1. **Upload button** ("📎 Attach" or similar icon)
   - Opens file picker on click
   - Allows multi-select
2. **Scope selector** (radio buttons / toggle):
   - ◉ **Conversation** (default) — Only visible in this chat
   - ○ **Project** — Visible to all conversations in this project
3. **Progress feedback:**
   - Upload progress bar per file
   - "Uploading..." spinner
   - Success/error toast notification

### File Display in Chat

**After upload:**
- Thumbnail preview of image (if image format)
- Metadata row: `filename | size | scope badge`
- Delete button (appears on hover)
- Scope badge styling:
  - **Conversation:** Blue/teal container or label
  - **Project:** Purple/gold container or label

**Example UI:**
```
┌─ image_abc123.png (2.3 MB) [Conversation] ✕
│  [Thumbnail preview]
└─────────────────────────────────────────────
```

### Artifact Panel (Optional)

**Location:** Sidebar or modal accessible from chat

**Features:**
- Filter: Conversation / Project / Both
- Search by filename
- List view with thumbnails
- Bulk delete option
- Shows creation date

---

## Data Flow

### Upload Workflow

```
1. User selects file(s) + scope (Conversation/Project) in UI
2. Browser validates: file size ≤ 50MB
3. POST /api/artifacts/upload
   Request body: multipart/form-data
   - file: binary
   - scope: 'conversation' | 'project'
   - conversation_id: int (if conversation scope)
   - project_id: int (if project scope)
4. Backend:
   a. Validate scope + IDs
   b. Create target directory if needed
   c. Generate UUID prefix + sanitize filename
   d. Write file to disk at {scope_dir}/{uuid_filename}
   e. Create Artifact DB record
      - scope: 'conversation' | 'project'
      - local_path: relative path
      - is_deleted: false
   f. Return: {artifact_id, filename, scope, type, size, created_at}
5. UI:
   a. Render thumbnail + metadata
   b. Broadcast to WebSocket (update artifact list)
6. Agent can now call list_artifact_images() + read_artifact_image()
```

### Agent Reading Workflow

```
1. Agent decides to read artifact (based on conversation context)
2. Agent calls list_artifact_images(scope='conversation')
   Response: [{id, filename, type, size, scope, created_at}, ...]
3. Agent calls read_artifact_image(artifact_id=123)
   Response: {id, filename, base64_content, content_type, ...}
4. Agent passes base64 to Claude's vision API for analysis
5. Agent includes findings in response to user
```

### Deletion Workflow

```
1. User clicks delete button on artifact thumbnail/panel
2. DELETE /api/artifacts/{artifact_id}
   Request: {confirm: true}
3. Backend:
   a. Query Artifact by ID (verify exists, not deleted)
   b. Hard delete file from disk using local_path
   c. Hard delete Artifact row from database
   d. Return: {success: true}
4. UI:
   a. Remove thumbnail from view
   b. Remove from artifact list
   c. Toast: "Deleted"
5. Agent can no longer access deleted artifact (file + DB record gone)
```

---

## Error Handling

### Upload Errors

| Scenario | Status | Response |
|----------|--------|----------|
| File > 50MB | 413 | `{error: "File too large (max 50MB)"}` |
| Invalid path/permissions | 500 | `{error: "Failed to save file"}` |
| Duplicate filename | 200 | Auto-rename: `image.png` → `image_1718221200.png` |
| Network interruption | Client retry | Browser handles with exponential backoff |

### Read Errors

| Scenario | Response |
|----------|----------|
| Artifact ID not found | `{error: "Artifact not found or was deleted"}` |
| File deleted since list | `{error: "File not found on disk"}` |
| Unsupported format (e.g., .exe) | `{error: "Unsupported file type"}` (graceful, no crash) |
| Access denied | `{error: "Access denied"}` |

### Edge Cases

| Case | Handling |
|------|----------|
| Same file uploaded twice | Both appear as separate artifacts; user deletes dupes if desired |
| Conversation deleted | Cascade-delete artifacts + files from disk |
| Project deleted | Cascade-delete project artifacts + files from disk |
| Concurrent uploads to same conversation | Server queues uploads; process sequentially |
| User switches conversations mid-upload | Upload completes to original conversation |
| Agent tries to read deleted artifact | Tool returns `{error: 'Artifact not found...'}` |

---

## Implementation Details

### New API Endpoint

**POST /api/artifacts/upload**
- Handler: `atria/web/routes/artifacts.py` (extend existing file)
- Request: `multipart/form-data` with `file`, `scope`, `conversation_id`/`project_id`
- Response: `{artifact_id, filename, scope, type, size, created_at}`
- Validation: File size, scope value, IDs exist in DB

**DELETE /api/artifacts/{artifact_id}**
- Extend existing endpoint
- Behavior: Hard delete (file + DB)

### New Agent Tools

**Handler location:** `atria/core/context_engineering/tools/handlers/artifacts_handler.py`
- Class: `ArtifactsToolHandler`
- Methods: `list_artifact_images()`, `read_artifact_image()`
- Uses: `ArtifactRepository` for DB queries
- Uses: `Path` / `os` for file I/O

**Tool registration:** Update `atria/core/context_engineering/tools/registry.py`
- Register `list_artifact_images` with schema
- Register `read_artifact_image` with schema

### Database Queries

**Add to ArtifactRepository:**
- `list_by_conversation_and_scope(conversation_id, scope)`
- `list_by_project_and_scope(project_id, scope)`
- Update `get_by_id()` to include scope

### File I/O

- Use `pathlib.Path` for cross-platform path handling
- Generate UUID prefix via `uuid.uuid4()`
- Sanitize filenames: remove `/`, `\`, null bytes, etc.
- Read files in binary mode for base64 encoding

### Frontend (React/Vite)

**New components:**
- `<FileUploadWidget />` — File input + scope selector
- `<ArtifactThumbnail />` — Thumbnail + metadata + delete button
- `<ArtifactPanel />` (optional) — Sidebar view of all artifacts

**State management (Zustand):**
- Add `artifacts: Artifact[]` to conversation store
- Add `uploadProgress: {[key]: progress}` for multi-file uploads
- Dispatch WebSocket events on upload success

---

## Testing Requirements

**Unit Tests:**
- Tool handlers: `list_artifact_images()`, `read_artifact_image()` with various scopes/IDs
- File I/O: Sanitize filename, UUID generation, disk I/O
- Database: Artifact creation, queries by scope, hard delete cascade

**Integration Tests:**
- E2E upload: POST `/api/artifacts/upload`, verify file on disk + DB record
- E2E deletion: DELETE `/api/artifacts/{id}`, verify file + DB record removed
- E2E agent reading: Agent calls tools, receives artifact data

**Manual Testing:**
- Upload image via web UI (conversation scope)
- Upload image via web UI (project scope)
- Agent reads uploaded image and analyzes it
- Delete image; verify agent can no longer access it
- Upload same filename twice; verify rename works
- Upload 50MB+ file; verify rejection

---

## Future Enhancements

- Versioning: Keep history of uploaded files
- Sharing: Allow project artifacts to be shared across users
- Compression: Auto-compress large images before storage
- OCR: Extract text from images for searchability
- Tags/Metadata: User-defined tags on artifacts
- Artifact expiration: Auto-delete after N days

---

## Success Criteria

✅ Users can upload files via web UI (conversation or project scope)  
✅ Uploaded files stored in `.artifacts/` with proper directory structure  
✅ Agent has access to `list_artifact_images()` and `read_artifact_image()` tools  
✅ Agent can analyze images (base64 passed to vision API)  
✅ Hard delete removes files from disk and database  
✅ UI shows thumbnails + scope badges  
✅ Concurrent uploads handled gracefully  
✅ All error cases return meaningful messages  
