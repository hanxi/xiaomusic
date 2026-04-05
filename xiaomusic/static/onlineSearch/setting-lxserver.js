/*============================LXServer配置函数=================================*/
async function loadLxServerConfig() {
    try {
        const response = await fetch('/api/lxServer/load');
        const data = await response.json();
        if (data.success) {
            displayLxServerConfig(data.data);
        }
    } catch (error) {
        console.error('加载LXServer配置失败:', error);
    }
}

function displayLxServerConfig(config) {
    document.getElementById('lxserver-url').textContent = config.base_url || '';

    // 显示认证信息
    const username = config['x-user-name'] || '';
    const token = config['x-user-token'] || '';
    document.getElementById('lxserver-username').textContent = username && username !== 'x-user-name' ? username : '未设置';
    document.getElementById('lxserver-token').textContent = token && token !== 'your_token_here' ? '******' : '未设置';

    // 保存认证信息供编辑使用
    window.currentLxServerAuth = {
        'x-user-name': username,
        'x-user-token': token
    };

    // 显示可编辑的平台列表
    window.currentPlatforms = config.platforms || {};
    renderPlatformsList();

    // 显示提示信息，等待用户手动拉取
    document.getElementById('love-list-info').textContent = '';
    document.getElementById('love-list-info').style.color = '#999';
    document.getElementById('default-list-info').textContent = '';
    document.getElementById('default-list-info').style.color = '#999';
    document.getElementById('user-list-container').innerHTML = '<div class="empty-playlist"></div>';
}

function renderPlatformsList() {
    const container = document.getElementById('platforms-list');
    const platforms = window.currentPlatforms || {};
    const entries = Object.entries(platforms);

    if (entries.length === 0) {
        container.innerHTML = '<div class="empty">暂无配置平台</div>';
        return;
    }

    const html = entries.map(([key, name]) => `
        <div class="platform-item">
            <input type="text" class="platform-key" value="${key}" placeholder="缩写" disabled>
            <input type="text" class="platform-name" value="${name}" placeholder="平台名称" disabled>
            <button class="delete-platform-btn" onclick="deletePlatform('${key}')">删除</button>
        </div>
    `).join('');

    container.innerHTML = html;
}

function addPlatform() {
    const newKey = prompt('请输入平台缩写（如：tx, kg, kw）:');
    if (!newKey || newKey.trim() === '') return;

    const newName = prompt('请输入平台名称（如：QQ音乐）:');
    if (!newName || newName.trim() === '') return;

    window.currentPlatforms[newKey.trim()] = newName.trim();
    renderPlatformsList();
    savePlatforms();
}

function deletePlatform(key) {
    if (!confirm(`确定要删除平台 "${key}" 吗？`)) return;
    delete window.currentPlatforms[key];
    renderPlatformsList();
    savePlatforms();
}

function updatePlatformKey(oldKey, newKey) {
    if (oldKey === newKey) return;
    if (window.currentPlatforms[newKey]) {
        alert('该缩写已存在！');
        renderPlatformsList();
        return;
    }
    const name = window.currentPlatforms[oldKey];
    delete window.currentPlatforms[oldKey];
    window.currentPlatforms[newKey] = name;
    renderPlatformsList();
    savePlatforms();
}

function updatePlatformName(key, newName) {
    window.currentPlatforms[key] = newName;
    savePlatforms();
}

async function savePlatforms() {
    try {
        const response = await fetch('/api/lxServer/updatePlatforms', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platforms: window.currentPlatforms })
        });
        const data = await response.json();
        if (!data.success) {
            alert(`保存失败：${data.error}`);
        }
    } catch (error) {
        console.error('保存平台配置失败:', error);
    }
}

function editLxServerUrl() {
    const urlElement = document.getElementById('lxserver-url');
    const currentUrl = urlElement.textContent;
    const newUrl = prompt('请输入LXServer 接口地址（如: http://127.0.0.1:9527/api）', currentUrl);

    if (newUrl === null) return;

    if (newUrl.trim() === '') {
        alert('LXServer 接口地址不能为空！');
        return;
    }
    const flag = isValidUrl(newUrl);
    if (flag) {
        updateLxServerUrl(newUrl);
    } else {
        alert('请输入有效的接口地址！');
    }
}

function isValidUrl(url) {
    try {
        if (!url.match(/^https?:\/\//i)) {
            url = 'http://' + url;
        }
        const urlObj = new URL(url);
        const hostname = urlObj.hostname;
        const ipPattern = /^(\d{1,3}\.){3}\d{1,3}$/;
        const domainPattern = /^([\da-z-]+\.)+[a-z]{2,6}$/i;
        return !(!ipPattern.test(hostname) && !domainPattern.test(hostname));

    } catch (e) {
        return false;
    }
}

async function updateLxServerUrl(newUrl) {
    try {
        const response = await fetch('/api/lxServer/updateUrl', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ search_url: newUrl })
        });
        const data = await response.json();
        if (data.success) {
            await loadLxServerConfig();
        } else {
            alert(`更新失败：${data.error}`);
        }
    } catch (error) {
        alert(`更新出错：${error.message}`);
    }
}

async function testLxServer() {
    const urlElement = document.getElementById('lxserver-url');
    const baseUrl = urlElement.textContent;

    if (!baseUrl) {
        alert('请先配置 LXServer 接口地址！');
        return;
    }

    const testBtn = document.getElementById('test-lxserver-btn');
    const originalContent = testBtn.innerHTML;
    testBtn.innerHTML = '<span class="material-icons">sync</span><span>测试中...</span>';
    testBtn.disabled = true;
    try {
        const response = await fetch('/api/lxServer/test');
        const data = await response.json();
        if (data.success) {
            alert(`✅ 测试成功，可正常调用！`);
        } else {
            alert(`❌ 测试失败：${data.error || '未知错误'}`);
        }
    } catch (error) {
        alert(`❌ 连接失败：${error.message}\n请检查服务器是否开启或地址是否正确。`);
    } finally {
        testBtn.innerHTML = originalContent;
        testBtn.disabled = false;
    }
}

function editLxServerAuth() {
    const modal = document.getElementById('lxserverAuthModal');
    document.getElementById('lxserver-username-input').value = window.currentLxServerAuth?.['x-user-name'] || '';
    document.getElementById('lxserver-token-input').value = window.currentLxServerAuth?.['x-user-token'] || '';
    modal.style.display = 'flex';
}

function closeLxServerAuthModal() {
    document.getElementById('lxserverAuthModal').style.display = 'none';
}

async function confirmLxServerAuth() {
    const username = document.getElementById('lxserver-username-input').value.trim();
    const token = document.getElementById('lxserver-token-input').value.trim();

    if (!username || !token) {
        alert('用户名和Token都不能为空！');
        return;
    }

    try {
        const response = await fetch('/api/lxServer/updateAuth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                'x-user-name': username,
                'x-user-token': token
            })
        });
        const data = await response.json();
        if (data.success) {
            closeLxServerAuthModal();
            await loadLxServerConfig();
            alert('认证信息更新成功！');
        } else {
            alert(`更新失败：${data.error}`);
        }
    } catch (error) {
        alert(`更新出错：${error.message}`);
    }
}

function toggleTokenVisibility() {
    const tokenInput = document.getElementById('lxserver-token-input');
    const toggleIcon = document.getElementById('token-toggle-icon');
    if (tokenInput.type === 'password') {
        tokenInput.type = 'text';
        toggleIcon.textContent = 'visibility';
    } else {
        tokenInput.type = 'password';
        toggleIcon.textContent = 'visibility_off';
    }
}

async function loadUserPlaylist() {
    const loveListInfo = document.getElementById('love-list-info');
    const defaultListInfo = document.getElementById('default-list-info');
    const userListContainer = document.getElementById('user-list-container');

    try {
        const response = await fetch('/api/lxServer/userList');
        const data = await response.json();

        if (!data.success) {
            loveListInfo.textContent = `获取失败: ${data.error}`;
            defaultListInfo.textContent = `获取失败: ${data.error}`;
            userListContainer.innerHTML = `<div class="empty-playlist">获取失败: ${data.error}</div>`;
            return;
        }

        const playlistData = data.data;
        window.currentPlaylistData = playlistData;

        loveListInfo.innerHTML = `共 ${playlistData.loveList?.length || 0} 首歌曲`;
        loveListInfo.style.color = '#666';

        defaultListInfo.innerHTML = `共 ${playlistData.defaultList?.length || 0} 首歌曲`;
        defaultListInfo.style.color = '#666';

        // 渲染我喜欢的音乐歌单
        const loveSongs = playlistData.loveList || [];
        const loveListSongsContainer = document.getElementById('love-list-songs');
        if (loveListSongsContainer) {
            loveListSongsContainer.innerHTML = renderPlaylistSongs(loveSongs);
        }

        // 渲染默认歌单
        const defaultSongs = playlistData.defaultList || [];
        const defaultListSongsContainer = document.getElementById('default-list-songs');
        if (defaultListSongsContainer) {
            defaultListSongsContainer.innerHTML = renderPlaylistSongs(defaultSongs);
        }

        const userLists = playlistData.userList || [];
        if (userLists.length === 0) {
            userListContainer.innerHTML = '<div class="empty-playlist">暂无自定义歌单</div>';
        } else {
            userListContainer.innerHTML = userLists.map((list, index) => {
                const sourceName = window.currentPlatforms?.[list.source] || list.source || '未知';
                const songs = list.list || list.musicList || list.songs || [];
                const songCount = list.songCount || songs.length;
                return `
                    <div class="playlist-item-wrapper">
                        <div class="playlist-item" data-index="${index}">
                            <input type="checkbox" class="user-playlist-checkbox" value="${index}" onchange="updateDeleteButtonState()">
                            <span class="expand-icon" onclick="togglePlaylistExpand(event, ${index})">▶</span>
                            <div class="playlist-item-info">
                                <div class="playlist-item-name">${escapeHtml(list.name)}</div>
                                <div class="playlist-item-meta">${songCount} 首歌曲</div>
                            </div>
                            <span class="playlist-item-source">${escapeHtml(sourceName)}</span>
                        </div>
                        <div class="playlist-songs" id="playlist-songs-${index}" style="display: none;">
                            ${renderPlaylistSongs(songs)}
                        </div>
                    </div>
                `;
            }).join('');
        }

        // 绑定 love-list-checkbox 和 default-list-checkbox 的事件
        document.getElementById('love-list-checkbox')?.addEventListener('change', updateDeleteButtonState);
        document.getElementById('default-list-checkbox')?.addEventListener('change', updateDeleteButtonState);

        setupSelectAllCheckbox();

    } catch (error) {
        loveListInfo.textContent = '获取失败: 网络错误';
        defaultListInfo.textContent = '获取失败: 网络错误';
        userListContainer.innerHTML = '<div class="empty-playlist">获取失败: 网络错误</div>';
    }
}

function renderPlaylistSongs(songs) {
    if (!songs || songs.length === 0) {
        return '<div class="empty-songs">暂无歌曲</div>';
    }
    return songs.map((song, idx) => {
        const title = song.title || song.name || song.songName || '未知歌曲';
        const artist = song.artist || song.singer || song.artists || '未知歌手';
        const album = song.album || song.albumName || '';
        return `
            <div class="song-item">
                <span class="song-index">${idx + 1}</span>
                <div class="song-info">
                    <div class="song-title">${escapeHtml(title)}</div>
                    <div class="song-artist">${escapeHtml(artist)}${album ? ' - ' + escapeHtml(album) : ''}</div>
                </div>
            </div>
        `;
    }).join('');
}

function togglePlaylistExpand(event, index) {
    event.stopPropagation();
    const songsContainer = document.getElementById(`playlist-songs-${index}`);
    const expandIcon = event.target;
    if (songsContainer.style.display === 'none') {
        songsContainer.style.display = 'block';
        expandIcon.style.transform = 'rotate(90deg)';
    } else {
        songsContainer.style.display = 'none';
        expandIcon.style.transform = 'rotate(0deg)';
    }
}

function toggleLoveListExpand(event) {
    const songsContainer = document.getElementById('love-list-songs');
    if (songsContainer.style.display === 'none') {
        songsContainer.style.display = 'block';
        event.target.style.transform = 'rotate(90deg)';
    } else {
        songsContainer.style.display = 'none';
        event.target.style.transform = 'rotate(0deg)';
    }
}

function toggleDefaultListExpand(event) {
    const songsContainer = document.getElementById('default-list-songs');
    if (songsContainer.style.display === 'none') {
        songsContainer.style.display = 'block';
        event.target.style.transform = 'rotate(90deg)';
    } else {
        songsContainer.style.display = 'none';
        event.target.style.transform = 'rotate(0deg)';
    }
}

function setupSelectAllCheckbox() {
    const selectAllCheckbox = document.getElementById('select-all-playlists');
    const userListCheckboxes = document.querySelectorAll('.user-playlist-checkbox');

    selectAllCheckbox.addEventListener('change', function() {
        userListCheckboxes.forEach(cb => cb.checked = this.checked);
        updateDeleteButtonState();
    });
}

function updateDeleteButtonState() {
    const loveListCb = document.getElementById('love-list-checkbox');
    const defaultListCb = document.getElementById('default-list-checkbox');
    const userListCbs = document.querySelectorAll('.user-playlist-checkbox');
    const deleteBtn = document.getElementById('delete-playlist-btn');

    const hasSelection = loveListCb.checked || defaultListCb.checked ||
                        Array.from(userListCbs).some(cb => cb.checked);

    deleteBtn.disabled = !hasSelection;
}

async function deleteSelectedPlaylists() {
    const loveListCb = document.getElementById('love-list-checkbox');
    const defaultListCb = document.getElementById('default-list-checkbox');
    const userListCbs = document.querySelectorAll('.user-playlist-checkbox');
    const deleteBtn = document.getElementById('delete-playlist-btn');
    const statusDiv = document.getElementById('playlist-sync-status');
    const statusText = document.getElementById('sync-status-text');

    const deleteList = [];
    if (loveListCb.checked) deleteList.push('loveList');
    if (defaultListCb.checked) deleteList.push('defaultList');

    const selectedIndexes = Array.from(userListCbs)
        .filter(cb => cb.checked)
        .map(cb => parseInt(cb.value));

    if (deleteList.length === 0 && selectedIndexes.length === 0) {
        alert('请选择要删除的歌单');
        return;
    }

    if (!confirm(`确定要删除选中的 ${deleteList.length + selectedIndexes.length} 个歌单吗？`)) {
        return;
    }

    const originalContent = deleteBtn.innerHTML;
    deleteBtn.innerHTML = '<span class="material-icons">delete</span><span>删除中...</span>';
    deleteBtn.disabled = true;

    statusDiv.style.display = 'block';
    statusText.textContent = '正在删除歌单...';

    try {
        const response = await fetch('/api/lxServer/deletePlaylists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                deleteList: deleteList,
                userListIndexes: selectedIndexes
            })
        });
        const data = await response.json();

        if (data.success) {
            statusText.textContent = data.message;
            statusDiv.style.background = '#e8f5e9';
            statusDiv.style.borderColor = '#c8e6c9';
            statusDiv.style.color = '#2e7d32';
            loveListCb.checked = false;
            defaultListCb.checked = false;
            await loadUserPlaylist();
        } else {
            statusText.textContent = `删除失败: ${data.error}`;
            statusDiv.style.background = '#ffebee';
            statusDiv.style.borderColor = '#ffcdd2';
            statusDiv.style.color = '#c62828';
        }

    } catch (error) {
        statusText.textContent = `删除失败: ${error.message}`;
        statusDiv.style.background = '#ffebee';
        statusDiv.style.borderColor = '#ffcdd2';
        statusDiv.style.color = '#c62828';
    } finally {
        deleteBtn.innerHTML = originalContent;
        updateDeleteButtonState();
    }
}

async function clearXiaomusicPlaylists() {
    const statusDiv = document.getElementById('playlist-sync-status');
    const statusText = document.getElementById('sync-status-text');

    if (!confirm('确定要清空所有已转换为xiaomusic格式的歌单吗？')) {
        return;
    }

    try {
        const response = await fetch('/api/lxServer/clearXiaomusicPlaylists', {
            method: 'POST'
        });
        const data = await response.json();

        if (data.success) {
            statusText.textContent = data.message;
            statusDiv.style.background = '#e8f5e9';
            statusDiv.style.borderColor = '#c8e6c9';
            statusDiv.style.color = '#2e7d32';
        } else {
            statusText.textContent = `清空失败: ${data.error}`;
            statusDiv.style.background = '#ffebee';
            statusDiv.style.borderColor = '#ffcdd2';
            statusDiv.style.color = '#c62828';
        }

    } catch (error) {
        statusText.textContent = `清空失败: ${error.message}`;
        statusDiv.style.background = '#ffebee';
        statusDiv.style.borderColor = '#ffcdd2';
        statusDiv.style.color = '#c62828';
    }
}

async function refreshUserPlaylist() {
    await loadUserPlaylist();
}

async function fetchLxPlaylist() {
    const syncBtn = document.getElementById('sync-playlist-btn');
    const statusDiv = document.getElementById('playlist-sync-status');
    const statusText = document.getElementById('sync-status-text');

    const originalContent = syncBtn.innerHTML;
    syncBtn.innerHTML = '<span class="material-icons">sync</span><span>拉取中...</span>';
    syncBtn.disabled = true;

    statusDiv.style.display = 'block';
    statusText.textContent = '正在拉取LX用户歌单...';

    try {
        const response = await fetch('/api/lxServer/pullPlaylist');
        const data = await response.json();

        if (data.success) {
            statusText.textContent = data.message;
            statusDiv.style.background = '#e8f5e9';
            statusDiv.style.borderColor = '#c8e6c9';
            statusDiv.style.color = '#2e7d32';
            await loadUserPlaylist();
            // 成功提示3秒后自动关闭
            setTimeout(() => {
                statusDiv.style.display = 'none';
            }, 3000);
        } else {
            statusText.textContent = `拉取失败: ${data.error}`;
            statusDiv.style.background = '#ffebee';
            statusDiv.style.borderColor = '#ffcdd2';
            statusDiv.style.color = '#c62828';
        }

    } catch (error) {
        statusText.textContent = `拉取失败: ${error.message}`;
        statusDiv.style.background = '#ffebee';
        statusDiv.style.borderColor = '#ffcdd2';
        statusDiv.style.color = '#c62828';
    } finally {
        syncBtn.innerHTML = originalContent;
        syncBtn.disabled = false;
    }
}

async function convertToXiaomusic() {
    const loveListCb = document.getElementById('love-list-checkbox');
    const defaultListCb = document.getElementById('default-list-checkbox');
    const userListCbs = document.querySelectorAll('.user-playlist-checkbox');

    const selectedPlaylists = [];
    if (loveListCb?.checked) selectedPlaylists.push('loveList');
    if (defaultListCb?.checked) selectedPlaylists.push('defaultList');

    const playlistData = window.currentPlaylistData;
    if (!playlistData) {
        alert('请先拉取歌单');
        return;
    }

    const userListSelected = [];
    userListCbs.forEach((cb, idx) => {
        if (cb.checked && playlistData.userList?.[idx]) {
            userListSelected.push(playlistData.userList[idx].name);
        }
    });

    let confirmMsg;
    const totalSelected = selectedPlaylists.length + userListSelected.length;
    if (totalSelected > 0) {
        confirmMsg = `转换勾选的 ${totalSelected} 个歌单？`;
    } else {
        const allPlaylists = [];
        if (playlistData.loveList?.length) allPlaylists.push('我喜欢的音乐');
        if (playlistData.defaultList?.length) allPlaylists.push('默认歌单');
        playlistData.userList?.forEach(lst => {
            if (lst.songCount > 0) allPlaylists.push(lst.name);
        });
        if (allPlaylists.length === 0) {
            alert('没有可转换的歌单');
            return;
        }
        confirmMsg = `未勾选歌单，转换所有 ${allPlaylists.length} 个歌单？`;
    }

    if (!confirm(confirmMsg)) return;

    const convertBtn = document.getElementById('convert-playlist-btn');
    const statusDiv = document.getElementById('playlist-sync-status');
    const statusText = document.getElementById('sync-status-text');

    const originalContent = convertBtn.innerHTML;
    convertBtn.innerHTML = '<span class="material-icons">sync</span><span>转换中...</span>';
    convertBtn.disabled = true;

    statusDiv.style.display = 'block';
    statusText.textContent = '正在转换为xiaomusic格式...';

    try {
        const response = await fetch('/api/lxServer/convertPlaylist');
        const data = await response.json();

        if (data.success) {
            statusText.textContent = data.message;
            statusDiv.style.background = '#e8f5e9';
            statusDiv.style.borderColor = '#c8e6c9';
            statusDiv.style.color = '#2e7d32';
            setTimeout(() => {
                statusDiv.style.display = 'none';
            }, 3000);
        } else {
            statusText.textContent = `转换失败: ${data.error}`;
            statusDiv.style.background = '#ffebee';
            statusDiv.style.borderColor = '#ffcdd2';
            statusDiv.style.color = '#c62828';
        }

    } catch (error) {
        statusText.textContent = `转换失败: ${error.message}`;
        statusDiv.style.background = '#ffebee';
        statusDiv.style.borderColor = '#ffcdd2';
        statusDiv.style.color = '#c62828';
    } finally {
        convertBtn.innerHTML = originalContent;
        convertBtn.disabled = false;
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
