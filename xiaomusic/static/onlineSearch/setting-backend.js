/*============================后台类型配置函数=================================*/
async function loadBackConfInfo() {
    try {
        const response = await fetch('/api/back-conf/load');
        const data = await response.json();
        if (data.success) {
            displayBackConfInfo(data.data);
        }
    } catch (error) {
        console.error('加载后台配置失败:', error);
    }
}

function displayBackConfInfo(config) {
    const container = document.getElementById('backend-options');
    const apiOptions = config.api_options || [];
    const currentType = config.api_type || 1;
    // 保存当前类型到全局变量
    window.currentBackendType = currentType;
    window.selectedBackendType = currentType;

    const html = apiOptions.map(opt => `
        <div class="backend-option ${opt.type === currentType ? 'selected' : ''}"
             data-type="${opt.type}" onclick="selectBackendType(${opt.type})">
            <div class="backend-option-title">
                <span class="radio-circle"></span>
                ${opt.name}
            </div>
            <div class="backend-option-desc">
                ${opt.type === 1 ? '使用 MusicFree 插件搜索音乐' : '使用 LXServer 接口搜索音乐'}
            </div>
        </div>
    `).join('');

    container.innerHTML = html;

    // 根据当前选择显示/隐藏配置区域，并加载对应数据
    updateConfigAreas(currentType);
}

function selectBackendType(apiType) {
    const currentType = window.currentBackendType;

    if (parseInt(apiType) === currentType) {
        return;
    }

    if (!confirm('确定要切换接口生态吗？')) {
        return;
    }

    window.selectedBackendType = apiType;
    saveBackendType();
}

async function saveBackendType() {
    const newType = window.selectedBackendType;
    const currentType = window.currentBackendType;

    try {
        const response = await fetch('/api/back-conf/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ api_type: newType })
        });
        const data = await response.json();
        if (data.success) {
            // 更新全局变量
            window.currentBackendType = newType;
            alert('切换成功');
            // 根据新类型更新配置区域
            updateConfigAreas(newType);
            // 更新选项卡选中状态
            document.querySelectorAll('.backend-option').forEach(el => {
                el.classList.remove('selected');
                if (parseInt(el.dataset.type) === newType) {
                    el.classList.add('selected');
                }
            });
            // 加载对应类型的数据
            if (newType === 1) {
                loadPlugins();
                await loadPluginSource();
            } else {
                await loadLxServerConfig();
            }
        } else {
            alert(`保存失败：${data.error}`);
        }
    } catch (error) {
        alert(`保存出错：${error.message}`);
    }
}

function updateConfigAreas(apiType) {
    const pluginArea = document.getElementById('plugin-config-area');
    const lxserverArea = document.getElementById('lxserver-config-area');

    // 获取需要控制显示的按钮
    const pluginUploadBtn = document.getElementById('plugin-upload-btn');
    const pluginRefreshBtn = document.getElementById('plugin-refresh-btn');
    const pluginChannelBtn = document.getElementById('plugin-channel-btn');
    const lxserverProjectBtn = document.getElementById('lxserver-project-btn');

    if (apiType === 1) {
        // MusicFree 模式：显示插件相关按钮，隐藏 LX Server 按钮
        pluginArea.style.display = 'block';
        lxserverArea.style.display = 'none';

        pluginUploadBtn.style.display = 'inline-flex';
        pluginRefreshBtn.style.display = 'inline-flex';
        pluginChannelBtn.style.display = 'inline-flex';
        lxserverProjectBtn.style.display = 'none';
    } else {
        // LXServer 模式：显示 LX Server 按钮，隐藏插件相关按钮
        pluginArea.style.display = 'none';
        lxserverArea.style.display = 'block';

        pluginUploadBtn.style.display = 'none';
        pluginRefreshBtn.style.display = 'none';
        pluginChannelBtn.style.display = 'none';
        lxserverProjectBtn.style.display = 'inline-flex';
    }
}
