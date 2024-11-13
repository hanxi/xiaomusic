'use strict'
var cacheStorageKey = 'xiaomusic-key';
let cacheName = 'xiaomusic-cache'; // 缓存名字

var cacheList = [ // 所需缓存的文件
  '/',
  "index.html"
]

self.addEventListener('install', function(e) {
  console.log('Cache event!')
  e.waitUntil(
    // 安装服务者时，对需要缓存的文件进行缓存
    caches.open(cacheStorageKey).then(function(cache) {
      console.log('Adding to Cache:', cacheList)
      return cache.addAll(cacheList)
    }).then(function() {
      console.log('Skip waiting!')
      return self.skipWaiting()
    })
  )
})

self.addEventListener('activate', function(e) {
  // 判断地址是不是需要实时去请求，是就继续发送请求
  console.log('Activate event')
  e.waitUntil(
    Promise.all(
      caches.keys().then(cacheNames => {
        return cacheNames.map(name => {
          if (name !== cacheStorageKey) {
            return caches.delete(name)
          }
        })
      })
    ).then(() => {
      console.log('Clients claims.')
      return self.clients.claim()
    })
  )
})

self.addEventListener('fetch', function(e) {
  // 匹配到缓存资源，就从缓存中返回数据
  e.respondWith(
    caches.match(e.request).then(function(response) {
      if (response != null) {
        console.log('Using cache for:', e.request.url)
        return response
      }
      console.log('Fallback to fetch:', e.request.url)
      return fetch(e.request.url)
    })
  )
})
