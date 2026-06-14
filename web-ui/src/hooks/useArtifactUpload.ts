import { useState, useCallback, useRef } from 'react';
import type { Artifact } from '../types';
import { validateFileSize } from '../utils/fileUtils';

export type UploadScope = 'conversation' | 'project';

const UPLOAD_TIMEOUT_MS = 60000; // 60 seconds

interface UseArtifactUploadOptions {
  maxFileSizeMB?: number;
  onSuccess?: (artifact: Artifact) => void;
  onError?: (error: string) => void;
}

export function useArtifactUpload(options: UseArtifactUploadOptions = {}) {
  const { maxFileSizeMB = 50, onSuccess, onError } = options;
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const upload = useCallback(
    async (
      file: File,
      scope: UploadScope,
      conversationId?: number,
      projectId?: number,
    ): Promise<Artifact | null> => {
      try {
        setError(null);

        // Validate file
        if (!validateFileSize(file, maxFileSizeMB)) {
          const errorMsg = `File size exceeds ${maxFileSizeMB}MB limit`;
          setError(errorMsg);
          onError?.(errorMsg);
          return null;
        }

        setUploading(true);
        setProgress((prev) => ({ ...prev, [file.name]: 0 }));

        // Create FormData
        const formData = new FormData();
        formData.append('file', file);
        formData.append('scope', scope);
        if (conversationId) {
          formData.append('conversation_id', conversationId.toString());
        }
        if (projectId) {
          formData.append('project_id', projectId.toString());
        }

        // Upload with progress tracking
        const xhr = new XMLHttpRequest();
        xhrRef.current = xhr;

        // Set timeout
        xhr.timeout = UPLOAD_TIMEOUT_MS;

        // Track progress
        xhr.upload.addEventListener('progress', (e) => {
          if (e.lengthComputable) {
            const percentComplete = (e.loaded / e.total) * 100;
            setProgress((prev) => ({
              ...prev,
              [file.name]: Math.round(percentComplete),
            }));
          }
        });

        // Wrap in promise
        const response = await new Promise<any>((resolve, reject) => {
          xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve(JSON.parse(xhr.responseText));
            } else {
              // Better error messages based on status
              if (xhr.status === 413) {
                reject(new Error(`File too large (max ${maxFileSizeMB}MB)`));
              } else if (xhr.status === 400) {
                reject(new Error('Invalid file or scope'));
              } else if (xhr.status >= 500) {
                reject(new Error('Server error, please try again'));
              } else {
                reject(new Error(`Upload failed: ${xhr.statusText || 'Unknown error'}`));
              }
            }
          });

          xhr.addEventListener('error', () => {
            reject(new Error('Upload failed: Network error'));
          });

          xhr.addEventListener('abort', () => {
            reject(new Error('Upload cancelled'));
          });

          xhr.addEventListener('timeout', () => {
            reject(new Error('Upload took too long, please try again'));
          });

          xhr.open('POST', '/api/artifacts/upload');
          xhr.send(formData);
        });

        const artifact: Artifact = response.artifact || response;

        setProgress((prev) => {
          const updated = { ...prev };
          delete updated[file.name];
          return updated;
        });
        setUploading(false);
        onSuccess?.(artifact);

        return artifact;
      } catch (err) {
        const errorMsg = err instanceof Error ? err.message : 'Upload failed';
        setError(errorMsg);
        onError?.(errorMsg);
        setProgress((prev) => {
          const updated = { ...prev };
          delete updated[file.name];
          return updated;
        });
        setUploading(false);
        return null;
      }
    },
    [maxFileSizeMB, onSuccess, onError],
  );

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  const abort = useCallback(() => {
    if (xhrRef.current) {
      xhrRef.current.abort();
      setError('Upload cancelled');
      setUploading(false);
      setProgress({});
    }
  }, []);

  return {
    upload,
    uploading,
    progress,
    error,
    clearError,
    abort,
  };
}
