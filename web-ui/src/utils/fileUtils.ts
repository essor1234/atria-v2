/**
 * File utility functions for artifact management.
 */

/**
 * Format file size from bytes to human-readable string.
 * @param bytes - File size in bytes
 * @returns Formatted file size string (e.g., "1.5 MB")
 */
export function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const k = 1024;
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${units[i]}`;
}

/**
 * Get MIME type based on filename.
 * @param filename - Name of the file
 * @returns MIME type string
 */
export function getMimeType(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';

  const mimeMap: Record<string, string> = {
    // Images
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    gif: 'image/gif',
    webp: 'image/webp',
    svg: 'image/svg+xml',
    // Documents
    pdf: 'application/pdf',
    doc: 'application/msword',
    docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    txt: 'text/plain',
    md: 'text/markdown',
    // Code
    json: 'application/json',
    js: 'application/javascript',
    ts: 'application/typescript',
    py: 'text/plain',
    html: 'text/html',
    css: 'text/css',
  };

  return mimeMap[ext] || 'application/octet-stream';
}

/**
 * Check if file is an image based on filename.
 * @param filename - Name of the file
 * @returns True if file is an image
 */
export function isImageFile(filename: string): boolean {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'];
  return imageExts.includes(ext);
}

/**
 * Validate file size against maximum allowed size.
 * @param file - File to validate
 * @param maxMB - Maximum file size in megabytes (default: 50 MB)
 * @returns True if file size is valid
 */
export function validateFileSize(file: File, maxMB: number = 50): boolean {
  const maxBytes = maxMB * 1024 * 1024;
  return file.size <= maxBytes;
}

/**
 * Get file extension from filename.
 * @param filename - Name of the file
 * @returns File extension (without dot)
 */
export function getFileExtension(filename: string): string {
  return filename.split('.').pop()?.toLowerCase() || '';
}

/**
 * Generate a preview URL for a file if it's an image.
 * @param file - File to generate preview for
 * @returns Promise resolving to data URL or null
 */
export function generateImagePreview(file: File): Promise<string | null> {
  return new Promise((resolve) => {
    if (!isImageFile(file.name)) {
      resolve(null);
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      resolve(e.target?.result as string);
    };
    reader.onerror = () => {
      resolve(null);
    };
    reader.readAsDataURL(file);
  });
}
