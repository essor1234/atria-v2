Read an artifact image file and return its content as base64.

Retrieves the binary content of a stored artifact image and encodes it as base64 for use in vision models or display. Supports PNG, JPG, JPEG, GIF, WebP, and SVG formats.

**Supported Formats:**
- PNG (.png)
- JPEG (.jpg, .jpeg)
- GIF (.gif)
- WebP (.webp)
- SVG (.svg)

**File Size Limit:** 10MB maximum

**Returns:**
- Base64-encoded image data with appropriate MIME type
- MIME type mapping: png→image/png, jpg/jpeg→image/jpeg, gif→image/gif, webp→image/webp, svg→image/svg+xml
