import React, { useRef, useState, useCallback } from 'react';
import { CloudUpload } from 'lucide-react';
import { useArtifactUpload, type UploadScope } from '../hooks/useArtifactUpload';
import { formatFileSize } from '../utils/fileUtils';

interface FileUploadWidgetProps {
  conversationId?: number;
  projectId?: number;
  onUploadComplete?: (fileCount: number) => void;
  maxFileSizeMB?: number;
  className?: string;
}

export function FileUploadWidget({
  conversationId,
  projectId,
  onUploadComplete,
  maxFileSizeMB = 50,
  className = '',
}: FileUploadWidgetProps) {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [scope, setScope] = useState<UploadScope>('conversation');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const { upload, uploading, progress, error, clearError } = useArtifactUpload({
    maxFileSizeMB,
    onError: (err) => {
      console.error('Upload error:', err);
    },
  });

  const handleFileInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.currentTarget.files;
      if (files) {
        const newFiles = Array.from(files);
        setSelectedFiles((prev) => [...prev, ...newFiles]);
        e.currentTarget.value = ''; // Reset input
      }
    },
    [],
  );

  const handleRemoveFile = useCallback((index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const handleScopeChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setScope(e.target.value as UploadScope);
  }, []);

  const handleClick = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragEnter = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files) {
      const newFiles = Array.from(files);
      setSelectedFiles((prev) => [...prev, ...newFiles]);
    }
  }, []);

  const handleUpload = async () => {
    if (selectedFiles.length === 0) return;

    let uploadedCount = 0;

    for (const file of selectedFiles) {
      const result = await upload(file, scope, conversationId, projectId);
      if (result) {
        uploadedCount++;
      }
    }

    if (uploadedCount > 0) {
      setSelectedFiles([]);
      onUploadComplete?.(uploadedCount);
    }
  };

  const totalSize = selectedFiles.reduce((sum, file) => sum + file.size, 0);
  const isValid = selectedFiles.length > 0 && !uploading;

  return (
    <div className={`upload-widget ${className}`}>
      <div className="space-y-4">
        {/* Scope Selector */}
        <div className="flex gap-4">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="scope"
              value="conversation"
              checked={scope === 'conversation'}
              onChange={handleScopeChange}
              disabled={uploading}
              className="w-4 h-4"
            />
            <span className="text-sm font-medium">Conversation Scope</span>
          </label>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="radio"
              name="scope"
              value="project"
              checked={scope === 'project'}
              onChange={handleScopeChange}
              disabled={uploading}
              className="w-4 h-4"
            />
            <span className="text-sm font-medium">Project Scope</span>
          </label>
        </div>

        {/* File Input with Drag and Drop */}
        <div
          className={`border-2 border-dashed rounded-lg p-6 text-center transition-all cursor-pointer ${
            isDragging
              ? 'border-blue-400 bg-blue-50 shadow-soft'
              : 'border-hairline-soft hover:border-hairline'
          }`}
          onClick={handleClick}
          onDragOver={handleDragOver}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileInputChange}
            disabled={uploading}
            className="hidden"
          />
          <CloudUpload className="w-8 h-8 mx-auto mb-2 text-text-muted" />
          <p className="text-sm font-medium text-text-secondary">Click to select files</p>
          <p className="text-xs text-text-muted mt-1">or drag and drop</p>
          <p className="text-xs text-text-muted mt-2">Max {maxFileSizeMB}MB per file</p>
        </div>

        {/* Selected Files List */}
        {selectedFiles.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-medium text-text-secondary">Selected Files ({selectedFiles.length})</h3>
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {selectedFiles.map((file, index) => (
                <div key={`${file.name}-${index}`} className="flex items-center justify-between bg-surface-soft p-2 rounded">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-text-secondary truncate">{file.name}</p>
                    <p className="text-xs text-text-muted">{formatFileSize(file.size)}</p>
                  </div>
                  {progress[file.name] !== undefined && (
                    <div className="flex-shrink-0 ml-2 w-16 h-1 bg-gray-200 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-blue-500 transition-all duration-base"
                        style={{ width: `${progress[file.name]}%` }}
                      />
                    </div>
                  )}
                  {progress[file.name] === undefined && (
                    <button
                      onClick={() => handleRemoveFile(index)}
                      disabled={uploading}
                      className="flex-shrink-0 ml-2 p-1 text-text-muted hover:text-semantic-danger disabled:opacity-50"
                    >
                      ✕
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">Total: {formatFileSize(totalSize)}</span>
            </div>
          </div>
        )}

        {/* Error Message */}
        {error && (
          <div className="bg-red-50 border border-semantic-danger rounded-lg p-3 flex items-start justify-between">
            <div>
              <p className="text-sm font-medium text-semantic-danger">{error}</p>
            </div>
            <button
              onClick={clearError}
              className="text-semantic-danger hover:opacity-80"
            >
              ✕
            </button>
          </div>
        )}

        {/* Action Buttons */}
        {selectedFiles.length > 0 && (
          <div className="flex gap-2">
            <button
              onClick={handleUpload}
              disabled={!isValid}
              className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </button>
            <button
              onClick={() => setSelectedFiles([])}
              disabled={uploading}
              className="flex-1 px-4 py-2 border border-hairline-soft text-text-secondary rounded-lg font-medium hover:bg-surface-soft disabled:opacity-50 transition-colors"
            >
              Clear
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
