// API 基础配置
const API = {
    // 获取音乐列表
    async getMusicList() {
        const response = await fetch('/musiclist');
        return response.json();
    },

    // 获取多个音乐信息
    async getMusicInfos(songNames) {
        if (!Array.isArray(songNames)) {
            throw new Error('songNames must be an array');
        }
        
        const queryParams = songNames
            .map(name => `name=${encodeURIComponent(name)}`)
            .join('&');
            
        const response = await fetch(`/musicinfos?${queryParams}&musictag=true`);
        return response.json();
    },

    // 获取音乐信息
    async getMusicInfo(songName) {
        const response = await fetch(`/musicinfo?name=${encodeURIComponent(songName)}&musictag=true`);
        return response.json();
    },

    // 获取当前播放状态
    async getPlayingStatus(did = 'web_device') {
        const response = await fetch(`/playingmusic?did=${did}`);
        const data = await response.json();
        localStorage.setItem('cur_music', data.cur_music);
        localStorage.setItem('cur_playlist', data.cur_playlist);
        return data;
    },

    // 播放歌单中的歌曲
    async playMusicFromList(did = 'web_device', listname, musicname) {
        const response = await fetch('/playmusiclist', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ did, listname, musicname })
        });
        return response.json();
    },

    // 发送控制命令
    async sendCommand(did = 'web_device', cmd) {
        const response = await fetch('/cmd', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ did, cmd })
        });
        return response.json();
    },

    // 设置音量
    async setVolume(did = 'web_device', volume) {
        const response = await fetch('/setvolume', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ did, volume })
        });
        return response.json();
    },

    // 获取音量
    async getVolume(did = 'web_device') {
        const response = await fetch(`/getvolume?did=${did}`);
        return response.json();
    },

    // 获取设置
    async getSettings() {
        const response = await fetch('/getsetting');
        return response.json();
    },

    // 保存设置
    async saveSettings(settings) {
        const response = await fetch('/savesetting', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(settings)
        });
        return response.text();
    },

    // 获取所有自定义歌单
    async getPlaylistNames() {
        const response = await fetch('/playlistnames');
        return response.json();
    },

    // 获取歌单中的歌曲
    async getPlaylistMusics(name) {
        const response = await fetch(`/playlistmusics?name=${encodeURIComponent(name)}`);
        return response.json();
    },

    // 新增歌单
    async addPlaylist(name) {
        const response = await fetch('/playlistadd', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name })
        });
        return response.json();
    },

    // 删除歌单
    async deletePlaylist(name) {
        const response = await fetch('/playlistdel', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name })
        });
        return response.json();
    },

    // 修改歌单名称
    async updatePlaylistName(oldName, newName) {
        const response = await fetch('/playlistupdatename', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ oldname: oldName, newname: newName })
        });
        return response.json();
    },

    // 歌单添加歌曲
    async addMusicToPlaylist(playlistName, musicList) {
        const response = await fetch('/playlistaddmusic', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name: playlistName, music_list: musicList })
        });
        return response.json();
    },

    // 歌单删除歌曲
    async removeMusicFromPlaylist(playlistName, musicList) {
        const response = await fetch('/playlistdelmusic', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ name: playlistName, music_list: musicList })
        });
        return response.json();
    },

    // 播放命令
    commands: {
        PLAY_PAUSE: '暂停播放',
        PLAY_CONTINUE: '继续播放',
        PLAY_PREVIOUS: '上一首',
        PLAY_NEXT: '下一首',
        PLAY_MODE_SEQUENCE: '顺序播放',
        PLAY_MODE_RANDOM: '随机播放',
        PLAY_MODE_SINGLE: '单曲循环'
    }
};

// 导出 API 对象
window.API = API; 