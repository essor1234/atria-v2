# Artifacts File Upload & Management Components

This document describes the frontend components for file upload and artifact management in the Atria web UI.

## Overview

The artifact management system consists of:

1. **useArtifactUpload** - Custom React hook for handling file uploads
2. **FileUploadWidget** - UI component for selecting and uploading files
3. **ArtifactThumbnail** - Displays individual artifacts with preview
4. **ArtifactPanel** - Lists and filters artifacts with search
5. **fileUtils** - Utility functions for file operations
6. **artifacts store** - Zustand store for artifact state management

## Components

### FileUploadWidget

Upload button with scope selector and file management.

```tsx
import { FileUploadWidget } from '@/components/FileUploadWidget';

export function MyComponent() {
  return (
    <FileUploadWidget
      conversationId={123}
      projectId={456}
      maxFileSizeMB={50}
      onUploadComplete={(count) => {
        console.log(`Uploaded ${count} files`);
      }}
    />
  );
}
```

**Props:**
- `conversationId?: number` - ID of the conversation
- `projectId?: number` - ID of the project
- `maxFileSizeMB?: number` - Max file size in MB (default: 50)
- `onUploadComplete?: (fileCount: number) => void` - Callback after successful upload
- `className?: string` - Additional CSS classes

**Features:**
- Drag-and-drop file selection
- Scope selector (Conversation or Project)
- File validation and size checking
- Upload progress tracking
- Error handling with dismissible messages
- Individual file removal

### ArtifactPanel

List view for all artifacts with filtering and search.

```tsx
import { ArtifactPanel } from '@/components/ArtifactPanel';
import { useArtifactsStore } from '@/stores/artifacts';

export function MyComponent() {
  const artifacts = useArtifactsStore(s => s.artifacts['123'] ?? []);
  
  return (
    <ArtifactPanel
      artifacts={artifacts}
      isLoading={false}
      onDelete={(id) => {
        // Handle delete
      }}
      onPreview={(artifact) => {
        // Handle preview
      }}
    />
  );
}
```

**Props:**
- `artifacts: Artifact[]` - Array of artifacts to display
- `isLoading?: boolean` - Show loading state
- `onDelete?: (artifactId: number) => void` - Delete handler
- `onPreview?: (artifact: Artifact) => void` - Preview handler
- `className?: string` - Additional CSS classes

**Features:**
- Grid and list view modes
- Scope-based filtering (Conversation/Project/All)
- Full-text search by title
- Artifact type badges
- Scope color coding
- Hover delete buttons
- Artifact count display

### ArtifactThumbnail

Individual artifact card with preview and actions.

```tsx
import { ArtifactThumbnail } from '@/components/ArtifactThumbnail';

export function MyComponent() {
  return (
    <ArtifactThumbnail
      artifact={artifact}
      onDelete={(id) => {
        // Handle delete
      }}
      onPreview={(artifact) => {
        // Handle preview
      }}
    />
  );
}
```

**Props:**
- `artifact: Artifact` - The artifact to display
- `onDelete?: (artifactId: number) => void` - Delete handler
- `onPreview?: (artifact: Artifact) => void` - Preview handler
- `className?: string` - Additional CSS classes

**Features:**
- Image preview for image artifacts
- File type icon fallback
- Scope and type badges
- Hover delete button with confirmation
- Creation date tooltip
- Click to preview

### useArtifactUpload Hook

Custom hook for file upload handling.

```tsx
import { useArtifactUpload } from '@/hooks/useArtifactUpload';

export function MyComponent() {
  const { upload, uploading, progress, error, clearError } = useArtifactUpload({
    maxFileSizeMB: 50,
    onSuccess: (artifact) => {
      console.log('Upload successful:', artifact);
    },
    onError: (error) => {
      console.error('Upload failed:', error);
    },
  });

  const handleUpload = async () => {
    const file = new File(['content'], 'file.txt');
    const artifact = await upload(file, 'conversation', 123, 456);
  };

  return (
    <div>
      {uploading && <p>Uploading: {progress['file.txt']}%</p>}
      {error && <p className="error">{error}</p>}
      <button onClick={handleUpload}>Upload</button>
    </div>
  );
}
```

**Options:**
- `maxFileSizeMB?: number` - Max file size in MB (default: 50)
- `onSuccess?: (artifact: Artifact) => void` - Success callback
- `onError?: (error: string) => void` - Error callback

**Return:**
- `upload(file, scope, conversationId?, projectId?)` - Upload a file
- `uploading: boolean` - Whether upload is in progress
- `progress: Record<string, number>` - Upload progress by filename
- `error: string | null` - Current error message
- `clearError()` - Clear error message

## Utility Functions

### fileUtils

File handling utilities in `src/utils/fileUtils.ts`:

```tsx
import {
  formatFileSize,
  getMimeType,
  isImageFile,
  validateFileSize,
  getFileExtension,
  generateImagePreview,
} from '@/utils/fileUtils';

// Format bytes to human-readable string
formatFileSize(1048576); // "1.00 MB"

// Get MIME type from filename
getMimeType('photo.jpg'); // "image/jpeg"

// Check if file is image
isImageFile('photo.jpg'); // true

// Validate file size
const file = new File(['content'], 'test.txt');
validateFileSize(file, 50); // true (if < 50MB)

// Get file extension
getFileExtension('document.pdf'); // "pdf"

// Generate image preview (returns Promise<string | null>)
const preview = await generateImagePreview(imageFile);
```

## Store Integration

The artifacts store (`src/stores/artifacts.ts`) manages artifact state:

```tsx
import { useArtifactsStore } from '@/stores/artifacts';

export function MyComponent() {
  const store = useArtifactsStore();
  
  // Load artifacts
  await store.loadArtifacts('123');
  
  // Get artifacts for conversation
  const artifacts = store.artifacts['123'] ?? [];
  
  // Add artifact
  store.addArtifact('123', newArtifact);
  
  // Delete artifact
  await store.deleteArtifact('123', artifactId);
  
  // Toggle pin
  await store.togglePin('123', artifactId, isPinned);
  
  // Scan for artifacts
  await store.scanArtifacts('123');
}
```

**Store Actions:**
- `loadArtifacts(conversationId)` - Load artifacts from API
- `addArtifact(conversationId, artifact)` - Add artifact to store
- `setArtifacts(conversationId, artifacts)` - Set artifacts array
- `deleteArtifact(conversationId, artifactId)` - Delete artifact
- `togglePin(conversationId, artifactId, pinned)` - Toggle pin state
- `scanArtifacts(conversationId)` - Scan for new artifacts

## API Integration

The components integrate with the backend API:

**Upload Endpoint:** `POST /api/artifacts/upload`
- Multipart form data
- Fields: `file`, `scope`, `conversation_id?`, `project_id?`
- Returns: `{ artifact: Artifact }`

**List Artifacts:** `GET /api/artifacts?conversation_id={id}`
- Returns: `Artifact[]`

**Delete Artifact:** `DELETE /api/artifacts/{id}`

**Update Artifact:** `PATCH /api/artifacts/{id}`
- Fields: `title?`, `pinned?`, `payload_ref?`

## Type Definitions

The `Artifact` type is defined in `src/types/index.ts`:

```typescript
export interface Artifact {
  id: number;
  project_id: number | null;
  conversation_id: number | null;
  type: 'file' | 'code' | 'report' | 'image' | 'data';
  source_mode: string | null;
  title: string | null;
  pinned: boolean;
  payload_ref: string | null;
  preview: any | null;
  created_at: string;
  updated_at: string | null;
}
```

## Example: Complete Integration

```tsx
import { useState } from 'react';
import { FileUploadWidget } from '@/components/FileUploadWidget';
import { ArtifactPanel } from '@/components/ArtifactPanel';
import { useArtifactsStore } from '@/stores/artifacts';

export function ArtifactManager({ conversationId }) {
  const [selectedArtifact, setSelectedArtifact] = useState(null);
  const artifactsStore = useArtifactsStore();
  const artifacts = artifactsStore.artifacts[conversationId] ?? [];

  const handleUploadComplete = async () => {
    await artifactsStore.loadArtifacts(conversationId);
  };

  const handleDeleteArtifact = async (artifactId) => {
    await artifactsStore.deleteArtifact(conversationId, artifactId);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Upload Widget */}
      <div className="lg:col-span-1">
        <FileUploadWidget
          conversationId={conversationId}
          onUploadComplete={handleUploadComplete}
        />
      </div>

      {/* Artifact Panel */}
      <div className="lg:col-span-2 h-96">
        <ArtifactPanel
          artifacts={artifacts}
          onDelete={handleDeleteArtifact}
          onPreview={setSelectedArtifact}
        />
      </div>

      {/* Preview Modal */}
      {selectedArtifact && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center">
          <div className="bg-white p-6 rounded-lg max-w-2xl w-full">
            <h2>{selectedArtifact.title || 'Untitled'}</h2>
            {/* Preview content */}
            <button onClick={() => setSelectedArtifact(null)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

## CSS Styling

All components use Tailwind CSS classes. Custom styling can be added via the `className` prop.

Color scheme:
- **Conversation scope:** Blue (`bg-blue-100`, `text-blue-700`)
- **Project scope:** Purple (`bg-purple-100`, `text-purple-700`)
- **Success:** Green
- **Error:** Red
- **Neutral:** Gray

## Error Handling

Components handle errors gracefully:

1. **File validation errors** - Shown in FileUploadWidget
2. **Upload errors** - Displayed with clear messages
3. **Network errors** - Caught and handled
4. **Large files** - Validated before upload

Error messages are dismissible and state can be cleared with `clearError()`.

## Performance Considerations

- **Virtual scrolling** - Use for large artifact lists
- **Image preview generation** - Async to avoid blocking
- **Lazy loading** - Load artifacts on demand
- **Memoization** - Components use React.memo where appropriate
- **Progress tracking** - Real-time upload feedback

## Accessibility

- **ARIA labels** - Descriptive button labels
- **Keyboard navigation** - All controls accessible via keyboard
- **Focus management** - Proper focus states
- **Error announcements** - Clear error messages
- **Color contrast** - Meets WCAG standards

## Browser Support

- Chrome/Edge: Full support
- Firefox: Full support
- Safari: Full support
- Mobile browsers: Touch-optimized

## Future Enhancements

- [ ] Drag-and-drop file zones
- [ ] Multiple file upload progress
- [ ] Image cropping/editing
- [ ] File preview modal
- [ ] Artifact sharing
- [ ] Artifact versioning
- [ ] Batch operations
