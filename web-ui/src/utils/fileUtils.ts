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

