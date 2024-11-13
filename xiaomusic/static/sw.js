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

