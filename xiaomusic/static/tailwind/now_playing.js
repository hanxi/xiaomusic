const { createApp, ref, computed, onMounted, watch, onUnmounted } = Vue

createApp({
    setup() {
        const currentSong = ref({
            title: '',
            artist: '',
            album: '',
            cover: '',
            lyrics: [],
            tags: null,
            name: '' // 原始文件名
        })
        const isPlaying = ref(false)
        const currentTime = ref(0)
        const duration = ref(0)
        const volume = ref(1)
        const playMode = ref('repeat') // 'repeat', 'repeat_one', 'shuffle'
        const currentLyricIndex = ref(0)
        const isLoading = ref(false)
        const error = ref(null)
        const lyricsOffset = ref(0) // 歌词偏移值（秒）
        const showControlPanel = ref(true) // 控制面板显示状态
        
        // Toast 提示相关
        const showToast = ref(false)
        const toastMessage = ref('')
        const toastType = ref('alert-info')
        let toastTimer = null

        // 获取设备ID
        const deviceId = localStorage.getItem('cur_did') || 'web_device'
        // 保存设备ID到localStorage
        localStorage.setItem('cur_did', deviceId)

        // 从localStorage获取保存的歌词偏移值
        const savedOffset = localStorage.getItem('lyrics_offset')
        if (savedOffset !== null) {
            lyricsOffset.value = parseFloat(savedOffset)
        }

        // 调整歌词偏移
        function adjustLyricsOffset(seconds) {
            lyricsOffset.value += seconds
            // 保存偏移值到localStorage
            localStorage.setItem('lyrics_offset', lyricsOffset.value.toString())
            // 重新解析歌词
            if (currentSong.value.tags?.lyrics) {
                currentSong.value.lyrics = parseLyrics(currentSong.value.tags.lyrics)
                updateCurrentLyric()
            }
        }

        // 重置歌词偏移
        function resetLyricsOffset() {
            lyricsOffset.value = 0
            localStorage.setItem('lyrics_offset', '0')
            if (currentSong.value.tags?.lyrics) {
                currentSong.value.lyrics = parseLyrics(currentSong.value.tags.lyrics)
                updateCurrentLyric()
            }
        }

        // 初始化
        onMounted(async () => {
            // 获取并更新当前音量
            try {
                const volumeResponse = await API.getVolume(deviceId)
                if (volumeResponse.ret === 'OK') {
                    volume.value = parseInt(volumeResponse.volume)
                }
            } catch (err) {
                console.error('Error getting volume:', err)
            }
            
            // 开始定时获取播放状态
            updatePlayingStatus()
            setInterval(updatePlayingStatus, 1000)

            // 添加键盘事件监听
            document.addEventListener('keydown', handleKeyPress)
        })

        // 处理键盘事件
        async function handleKeyPress(event) {
            // 如果用户正在输入，不处理快捷键
            if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
                return
            }

            switch (event.code) {
                case 'Space': // 空格键：播放/暂停
                    event.preventDefault() // 防止页面滚动
                    await togglePlay()
                    break
                case 'ArrowLeft': // 左方向键：上一首
                    event.preventDefault()
                    await previousSong()
                    break
                case 'ArrowRight': // 右方向键：下一首
                    event.preventDefault()
                    await nextSong()
                    break
                case 'ArrowUp': // 上方向键：增加音量
                    event.preventDefault()
                    if (volume.value < 100) {
                        volume.value = Math.min(100, volume.value + 5)
                        await setVolume()
                    }
                    break
                case 'ArrowDown': // 下方向键：减小音量
                    event.preventDefault()
                    if (volume.value > 0) {
                        volume.value = Math.max(0, volume.value - 5)
                        await setVolume()
                    }
                    break
            }
        }

        // 在组件销毁时移除事件监听
        onUnmounted(() => {
            document.removeEventListener('keydown', handleKeyPress)
        })

        // 更新播放状态
        async function updatePlayingStatus() {
            try {
                error.value = null
                // 获取当前播放状态
                const status = await API.getPlayingStatus(deviceId)
                if (status.ret === 'OK') {
                    // 更新播放状态
                    isPlaying.value = status.is_playing
                    currentTime.value = status.offset || 0
                    duration.value = status.duration || 0

                    // 如果有正在播放的音乐且音乐发生改变
                    if (status.cur_music && status.cur_music !== currentSong.value.name) {
                        isLoading.value = true
                        try {
                            // 获取音乐详细信息
                            const musicInfo = await API.getMusicInfo(status.cur_music)
                            if (musicInfo && musicInfo.ret === 'OK') {
                                const tags = musicInfo.tags || {}
                                currentSong.value = {
                                    title: tags.title || musicInfo.name,
                                    artist: tags.artist || '未知歌手',
                                    album: tags.album || '未知专辑',
                                    cover: tags.picture || `/cover?name=${encodeURIComponent(musicInfo.name)}`,
                                    lyrics: parseLyrics(tags.lyrics || ''),
                                    tags: {
                                        year: tags.year,
                                        genre: tags.genre
                                    },
                                    name: musicInfo.name
                                }
                                // 更新当前歌词
                                updateCurrentLyric()
                            }
                        } finally {
                            isLoading.value = false
                        }
                    } else {
                        // 即使歌曲没有改变，也要更新当前歌词（因为时间在变化）
                        updateCurrentLyric()
                    }
                }
            } catch (err) {
                error.value = '获取播放状态失败'
                console.error('Error updating playing status:', err)
            }
        }

        // 解析歌词
        function parseLyrics(lyricsText) {
            if (!lyricsText) return []
            
            const lines = lyricsText.split('\n')
            const lyrics = []
            const timeRegex = /\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)/
            
            for (const line of lines) {
                const match = line.match(timeRegex)
                if (match) {
                    const minutes = parseInt(match[1])
                    const seconds = parseInt(match[2])
                    const milliseconds = parseInt(match[3])
                    const text = match[4].trim()
                    
                    // 只保留实际歌词行，排除元数据
                    if (text && !text.startsWith('[') && 
                        !text.includes('Lyricist') && !text.includes('Composer') && 
                        !text.includes('Producer') && !text.includes('Engineer') && 
                        !text.includes('Studio') && !text.includes('Company') &&
                        !text.includes('：') && !text.includes('Original') &&
                        !text.includes('Design') && !text.includes('Director') &&
                        !text.includes('Supervisor') && !text.includes('Promoter')) {
                        // 保存原始时间戳，不应用偏移
                        const time = minutes * 60 + seconds + (milliseconds / 1000)
                        lyrics.push({
                            time: Math.max(0, time),
                            text: text
                        })
                    }
                }
            }
            
            return lyrics.sort((a, b) => a.time - b.time)
        }

        // 更新当前歌词
        function updateCurrentLyric() {
            const lyrics = currentSong.value.lyrics
            if (!lyrics.length) return

            // 找到当前时间对应的歌词
            let foundIndex = -1
            // 应用偏移后的当前时间
            const currentTimeWithOffset = currentTime.value - lyricsOffset.value

            // 二分查找优化性能
            let left = 0
            let right = lyrics.length - 1

            while (left <= right) {
                const mid = Math.floor((left + right) / 2)
                const lyricTime = lyrics[mid].time

                if (mid === lyrics.length - 1) {
                    if (currentTimeWithOffset >= lyricTime) {
                        foundIndex = mid
                        break
                    }
                } else {
                    const nextTime = lyrics[mid + 1].time
                    if (currentTimeWithOffset >= lyricTime && currentTimeWithOffset < nextTime) {
                        foundIndex = mid
                        break
                    }
                }

                if (currentTimeWithOffset < lyricTime) {
                    right = mid - 1
                } else {
                    left = mid + 1
                }
            }

            // 如果找到新的歌词索引，更新显示
            if (foundIndex !== -1 && foundIndex !== currentLyricIndex.value) {
                currentLyricIndex.value = foundIndex

                // 获取歌词容器和当前歌词元素
                const container = document.querySelector('.lyrics-container')
                const currentLyric = container?.querySelector(`[data-index="${foundIndex}"]`)
                
                if (container && currentLyric) {
                    // 计算目标滚动位置，使当前歌词保持在容器中央
                    const containerHeight = container.offsetHeight
                    const lyricHeight = currentLyric.offsetHeight
                    const targetPosition = currentLyric.offsetTop - (containerHeight / 2) + (lyricHeight / 2)

                    // 使用平滑滚动
                    container.scrollTo({
                        top: targetPosition,
                        behavior: 'smooth'
                    })

                    // 添加高亮动画效果
                    currentLyric.style.transition = 'transform 0.3s ease-out'
                    currentLyric.style.transform = 'scale(1.05)'
                    setTimeout(() => {
                        currentLyric.style.transform = 'scale(1)'
                    }, 200)
                }
            }
        }

        // 显示提示
        function showMessage(message, type = 'info') {
            if (toastTimer) {
                clearTimeout(toastTimer)
            }
            toastMessage.value = message
            toastType.value = `alert-${type}`
            showToast.value = true
            toastTimer = setTimeout(() => {
                showToast.value = false
            }, 3000)
        }

        // 播放控制
        async function togglePlay() {
            const cmd = isPlaying.value ? API.commands.PLAY_PAUSE : API.commands.PLAY_CONTINUE
            const response = await API.sendCommand(deviceId, cmd)
            if (response.ret === 'OK') {
                isPlaying.value = !isPlaying.value
                showMessage(isPlaying.value ? '开始播放' : '暂停播放')
            }
        }

        async function previousSong() {
            const response = await API.sendCommand(deviceId, API.commands.PLAY_PREVIOUS)
            if (response.ret === 'OK') {
                showMessage('播放上一首')
            }
        }

        async function nextSong() {
            const response = await API.sendCommand(deviceId, API.commands.PLAY_NEXT)
            if (response.ret === 'OK') {
                showMessage('播放下一首')
            }
        }

        async function stopPlay() {
            const response = await API.sendCommand(deviceId, API.commands.PLAY_PAUSE)
            if (response.ret === 'OK') {
                isPlaying.value = false
                showMessage('停止播放')
            }
        }

        async function setPlayMode(mode) {
            let cmd
            let modeName
            switch (mode) {
                case 'repeat':
                    cmd = API.commands.PLAY_MODE_SEQUENCE
                    modeName = '顺序播放'
                    break
                case 'repeat_one':
                    cmd = API.commands.PLAY_MODE_SINGLE
                    modeName = '单曲循环'
                    break
                case 'shuffle':
                    cmd = API.commands.PLAY_MODE_RANDOM
                    modeName = '随机播放'
                    break
            }
            if (cmd) {
                const response = await API.sendCommand(deviceId, cmd)
                if (response.ret === 'OK') {
                    playMode.value = mode
                    showMessage(`切换到${modeName}模式`)
                }
            }
        }

        // 音量控制
        async function setVolume() {
            try {
                const volumeValue = parseInt(volume.value)
                const response = await API.setVolume(deviceId, volumeValue)
                if (response.ret === 'OK') {
                    showMessage(`音量: ${volumeValue}%`)
                } else {
                    console.error('Failed to set volume:', response)
                }
            } catch (error) {
                console.error('Error setting volume:', error)
            }
        }

        // 进度控制
        function seek() {
            // 更新歌词显示
            updateCurrentLyric()
        }

        // 时间格式化
        function formatTime(time) {
            const minutes = Math.floor(time / 60)
            const seconds = Math.floor(time % 60)
            return `${minutes}:${seconds.toString().padStart(2, '0')}`
        }

        return {
            currentSong,
            isPlaying,
            currentTime,
            duration,
            volume,
            playMode,
            currentLyricIndex,
            isLoading,
            error,
            lyricsOffset,
            showToast,
            toastMessage,
            toastType,
            showControlPanel,
            togglePlay,
            seek,
            setVolume,
            previousSong,
            nextSong,
            stopPlay,
            setPlayMode,
            formatTime,
            adjustLyricsOffset,
            resetLyricsOffset
        }
    }
}).mount('#app') 