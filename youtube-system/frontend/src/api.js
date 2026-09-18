import axios from 'axios'

const http = axios.create({ baseURL: '', timeout: 0 })

export function getUploadUrl(filename, size, contentType = 'video/mp4') {
  return http.post('/api/upload-url', {
    filename,
    size,
    content_type: contentType,
  })
}

export function uploadBinary(uploadPath, file, onProgress) {
  return http.post(`${uploadPath}?filename=${encodeURIComponent(file.name)}`, file, {
    headers: { 'Content-Type': 'application/octet-stream' },
    onUploadProgress: (e) => onProgress && onProgress(e),
  })
}

export function createVideo(videoId, title, description, filename) {
  return http.post('/api/videos', {
    video_id: videoId,
    title,
    description,
    filename,
  })
}

export function listVideos() {
  return http.get('/api/videos')
}

export function getVideo(id) {
  return http.get(`/api/videos/${id}`)
}

export function retryVideo(id) {
  return http.post(`/api/videos/${id}/retry`)
}

export function getStats() {
  return http.get('/api/stats')
}
