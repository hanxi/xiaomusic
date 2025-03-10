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
      name: '', // 原始文件名
      cur_playlist: '' // 当前歌单
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
    const deviceId = ref(localStorage.getItem('cur_did') || 'web_device')
    const audioPlayer = ref(null) // 添加 audioPlayer ref

    // Toast 提示相关
    const showToast = ref(false)
    const toastMessage = ref('')
    const toastType = ref('alert-info')
    let toastTimer = null

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

    // 初始化音频播放器
    function initAudioPlayer() {
      const audio = document.createElement('audio')
      audio.id = 'audio-player'
      document.body.appendChild(audio)
      audioPlayer.value = audio

      // 监听播放状态变化
      audio.addEventListener('play', () => {
        isPlaying.value = true
      })
      audio.addEventListener('pause', () => {
        isPlaying.value = false
      })
      audio.addEventListener('timeupdate', () => {
        currentTime.value = audio.currentTime
        updateCurrentLyric()
      })
      audio.addEventListener('loadedmetadata', () => {
        duration.value = audio.duration
      })
      audio.addEventListener('ended', () => {
        // 根据播放模式决定下一步操作
        if (playMode.value === 'repeat_one') {
          audio.currentTime = 0
          audio.play()
        } else {
          nextSong()
        }
      })
    }

    // 更新播放状态
    async function updatePlayingStatus() {
      try {
        error.value = null
        deviceId.value = localStorage.getItem('cur_did') || 'web_device'

        if (deviceId.value === 'web_device') {
          // Web播放模式 - 从localStorage获取当前播放信息
          const curMusic = localStorage.getItem('cur_music')
          const curPlaylist = localStorage.getItem('cur_playlist')

          if (curMusic && (!currentSong.value?.name || curMusic !== currentSong.value.name)) {
            isLoading.value = true
            try {
              // 获取音乐详细信息
              const musicInfo = await API.getMusicInfo(curMusic)
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
                  name: musicInfo.name,
                  cur_playlist: curPlaylist
                }

                // 如果音频播放器存在且URL不同，更新URL
                if (audioPlayer.value && audioPlayer.value.src !== musicInfo.url) {
                  audioPlayer.value.src = musicInfo.url
                  // 如果标记为正在播放，但实际已暂停，尝试恢复播放
                  if (isPlaying.value && audioPlayer.value.paused) {
                    try {
                      await audioPlayer.value.play()
                    } catch (e) {
                      console.error('Failed to resume playback:', e)
                      isPlaying.value = false
                    }
                  }
                }
              }
            } finally {
              isLoading.value = false
            }
          }

          // 更新播放状态
          if (audioPlayer.value) {
            isPlaying.value = !audioPlayer.value.paused
            currentTime.value = audioPlayer.value.currentTime || 0
            duration.value = audioPlayer.value.duration || 0
            updateCurrentLyric()
          }
        } else {
          // 设备播放模式 - 从API获取状态
          const status = await API.getPlayingStatus(deviceId.value)
          if (status.ret === 'OK') {
            // 更新播放状态
            isPlaying.value = status.is_playing
            currentTime.value = status.offset || 0
            duration.value = status.duration || 0
            currentSong.value.cur_playlist = status.cur_playlist || ''
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
                    name: musicInfo.name,
                    cur_playlist: status.cur_playlist
                  }
                }
              } finally {
                isLoading.value = false
              }
            }
            // 更新当前歌词
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
        // 滚动到当前歌词
        const container = document.querySelector('.lyrics-container')
        const currentLyric = container.querySelector(`[data-index="${foundIndex}"]`)
        if (currentLyric) {
          const containerHeight = container.clientHeight
          const lyricTop = currentLyric.offsetTop
          const lyricHeight = currentLyric.clientHeight
          // 计算滚动位置，使当前歌词在容器中垂直居中
          container.scrollTo({
            top: lyricTop - (containerHeight / 2) + (lyricHeight / 2),
            behavior: 'smooth'
          })
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
      try {
        if (deviceId.value === 'web_device') {
          // Web播放模式
          if (!currentSong.value?.name) {
            showMessage('没有可播放的歌曲', 'error')
            return
          }

          if (isPlaying.value) {
            if (audioPlayer.value) {
              audioPlayer.value.pause()
              isPlaying.value = false
              showMessage('暂停播放')
            }
          } else {
            try {
              // 获取最新的音乐URL
              const musicInfo = await API.getMusicInfo(currentSong.value.name)
              if (musicInfo && musicInfo.ret === 'OK') {
                if (audioPlayer.value) {
                  if (audioPlayer.value.src !== musicInfo.url) {
                    audioPlayer.value.src = musicInfo.url
                  }
                  await audioPlayer.value.play()
                  isPlaying.value = true
                  showMessage('开始播放')
                }
              } else {
                showMessage('获取音乐信息失败', 'error')
              }
            } catch (error) {
              console.error('Error getting music info:', error)
              showMessage('播放失败', 'error')
            }
          }
        } else {
          // 设备播放模式
          if (isPlaying.value) {
            // 如果正在播放，则暂停
            const response = await API.sendCommand(deviceId.value, API.commands.PLAY_PAUSE)
            if (response.ret === 'OK') {
              isPlaying.value = false
              showMessage('暂停播放')
            }
          } else {
            // 如果当前是暂停状态，获取当前歌曲信息并重新播放
            const status = await API.getPlayingStatus(deviceId.value)
            if (status.ret === 'OK' && status.cur_music && status.cur_playlist) {
              // 使用 playmusiclist 接口重新播放当前歌曲
              const response = await API.playMusicFromList(deviceId.value, status.cur_playlist, status.cur_music)
              if (response.ret === 'OK') {
                isPlaying.value = true
                showMessage('开始播放')
              } else {
                showMessage('播放失败', 'error')
              }
            } else {
              showMessage('获取播放信息失败', 'error')
            }
          }
        }
      } catch (error) {
        console.error('Error toggling play state:', error)
        showMessage('播放控制失败', 'error')
      }
    }

    async function previousSong() {
      const response = await API.sendCommand(deviceId.value, API.commands.PLAY_PREVIOUS)
      if (response.ret === 'OK') {
        showMessage('播放上一首')
      }
    }

    async function nextSong() {
      const response = await API.sendCommand(deviceId.value, API.commands.PLAY_NEXT)
      if (response.ret === 'OK') {
        showMessage('播放下一首')
      }
    }

    async function stopPlay() {
      const response = await API.sendCommand(deviceId.value, API.commands.PLAY_PAUSE)
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
        const response = await API.sendCommand(deviceId.value, cmd)
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
        const response = await API.setVolume(deviceId.value, volumeValue)
        if (response.ret === 'OK') {
          showMessage(`音量: ${volumeValue}%`)
          if (audioPlayer.value) {
            audioPlayer.value.volume = volumeValue / 100
          }
        } else {
          console.error('Failed to set volume:', response)
        }
      } catch (error) {
        console.error('Error setting volume:', error)
      }
    }

    // 手动调整进度
    async function seek() {
      try {
        if (deviceId.value === 'web_device') {
          // Web播放模式
          const audio = document.getElementById('audio-player')
          if (audio) {
            audio.currentTime = currentTime.value
          }
        } else {
          // 设备播放模式
          await API.sendCommand(deviceId.value, `seek ${Math.floor(currentTime.value)}`)
        }
        // 立即更新歌词显示
        updateCurrentLyric()
      } catch (error) {
        console.error('Error seeking:', error)
        showMessage('调整进度失败', 'error')
      }
    }

    // 格式化时间
    function formatTime(time) {
      if (!time) return '00:00'
      const minutes = Math.floor(time / 60)
      const seconds = Math.floor(time % 60)
      return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    }

    // 初始化
    onMounted(async () => {
      // 初始化音频播放器
      initAudioPlayer()

      // 获取并更新当前音量
      try {
        const volumeResponse = await API.getVolume(deviceId.value)
        if (volumeResponse.ret === 'OK') {
          volume.value = parseInt(volumeResponse.volume)
          if (audioPlayer.value) {
            audioPlayer.value.volume = volume.value / 100
          }
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

    // 在组件销毁时清理
    onUnmounted(() => {
      document.removeEventListener('keydown', handleKeyPress)
      if (audioPlayer.value) {
        audioPlayer.value.remove()
      }
    })

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
